// ais-matlab-helper runs on your own computer and opens your MATLAB when you
// click "Replay in MATLAB" in AIS Counter. It exists because a server in Docker,
// or on another machine, has no way to start anything on your computer: this
// asks the server for work every few seconds instead, so it needs no open port
// and works through any proxy. See app/routes/ais_matlab.py for the server side.
//
//	ais-matlab-helper connect <server url> <key>   once, with the key from Account
//	ais-matlab-helper                              leave running
//
// Everything here is the standard library, so one file per OS is the whole
// install.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const (
	version      = "1.0"
	pollInterval = 3 * time.Second
	// Longest a retry waits: the rate limiter's Retry-After is its whole window.
	maxBackoff = 60 * time.Second
	// The zip's folder is its images, a few MB, but a tunnel can be slow.
	downloadTimeout = 60 * time.Second
	keepRuns        = 20
	helperPath      = "/api/ais/matlab/helper/"
)

type config struct {
	Server       string `json:"server"`
	Key          string `json:"key"`
	Matlab       string `json:"matlab,omitempty"`
	InsecureHTTP bool   `json:"insecure_http,omitempty"`
}

type job struct {
	ID   string `json:"id"`
	Mode string `json:"mode"`
	Cell string `json:"cell"`
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == "connect" {
		if err := connect(os.Args[2:]); err != nil {
			fmt.Fprintln(os.Stderr, "error:", err)
			os.Exit(1)
		}
		return
	}
	flags := flag.NewFlagSet("ais-matlab-helper", flag.ExitOnError)
	matlab := flags.String("matlab", "", "the MATLAB to open, overriding your Account setting and the search")
	showVersion := flags.Bool("version", false, "print the version")
	flags.Usage = func() {
		fmt.Fprintln(os.Stderr, "usage:\n  ais-matlab-helper connect [--insecure-http] [--matlab path] <server url> <key>\n  ais-matlab-helper [--matlab path]")
	}
	flags.Parse(os.Args[1:])
	if *showVersion {
		fmt.Println(version)
		return
	}
	cfg, err := loadConfig()
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	if *matlab != "" {
		cfg.Matlab = *matlab
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := serve(ctx, cfg); err != nil && !errors.Is(err, context.Canceled) {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func connect(args []string) error {
	flags := flag.NewFlagSet("connect", flag.ExitOnError)
	insecure := flags.Bool("insecure-http", false, "allow plain http to another computer: anyone on the network could then run code here")
	matlab := flags.String("matlab", "", "the MATLAB to open, overriding your Account setting and the search")
	flags.Parse(args)
	if flags.NArg() != 2 {
		return errors.New("usage: ais-matlab-helper connect [--insecure-http] [--matlab path] <server url> <key>")
	}
	cfg := config{Server: strings.TrimRight(flags.Arg(0), "/"), Key: flags.Arg(1), Matlab: *matlab, InsecureHTTP: *insecure}
	if err := checkServer(cfg.Server, cfg.InsecureHTTP); err != nil {
		return err
	}
	// One poll proves the url and the key before anything is saved.
	if _, _, err := poll(context.Background(), cfg); err != nil {
		return err
	}
	if err := saveConfig(cfg); err != nil {
		return err
	}
	path, _ := configPath()
	fmt.Printf("Connected to %s. Saved to %s\nNow run: ais-matlab-helper\n", cfg.Server, path)
	return nil
}

// checkServer refuses to take code over a connection anyone could rewrite: what
// the server sends is run as you. Your own computer is the exception, because
// that is what a local Docker container is.
func checkServer(server string, insecure bool) error {
	parsed, err := url.Parse(server)
	if err != nil || parsed.Host == "" {
		return fmt.Errorf("%q is not a url: it should look like https://ais.example.org", server)
	}
	switch parsed.Scheme {
	case "https":
		return nil
	case "http":
		if isLoopback(parsed.Hostname()) {
			return nil
		}
		if insecure {
			fmt.Fprintln(os.Stderr, "warning: plain http: anyone on this network can read your key and run code on this computer")
			return nil
		}
		return fmt.Errorf("refusing plain http to %s: use https, or pass --insecure-http if you accept that anyone on the network could run code here", parsed.Hostname())
	}
	return fmt.Errorf("%q is not an http or https url", server)
}

func isLoopback(host string) bool {
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func serve(ctx context.Context, cfg config) error {
	if err := checkServer(cfg.Server, cfg.InsecureHTTP); err != nil {
		return err
	}
	fmt.Printf("Waiting for runs from %s (Ctrl-C stops)\n", cfg.Server)
	down := false
	for {
		next, wait, err := poll(ctx, cfg)
		var refused *refusedError
		switch {
		case errors.As(err, &refused):
			return fmt.Errorf("the server refused this helper's key (revoked or expired): get a new one from Account in AIS Counter and run connect again")
		case ctx.Err() != nil:
			return ctx.Err()
		case err != nil:
			if !down {
				fmt.Fprintln(os.Stderr, "cannot reach the server, still trying:", err)
			}
			down = true
		default:
			if down {
				fmt.Println("reconnected")
			}
			down = false
		}
		if next != nil {
			handle(ctx, cfg, *next)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(wait):
		}
	}
}

// refusedError is the server saying this key is finished, which no retry fixes.
type refusedError struct{ status int }

func (e *refusedError) Error() string { return fmt.Sprintf("the server answered %d", e.status) }

// poll asks for the next run, and how long to wait before asking again.
func poll(ctx context.Context, cfg config) (*job, time.Duration, error) {
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	response, err := request(ctx, cfg, http.MethodGet, "next", nil)
	if err != nil {
		return nil, pollInterval, err
	}
	defer response.Body.Close()
	switch response.StatusCode {
	case http.StatusNoContent:
		return nil, pollInterval, nil
	case http.StatusOK:
		var next job
		if err := json.NewDecoder(response.Body).Decode(&next); err != nil {
			return nil, pollInterval, fmt.Errorf("a run the server sent could not be read: %w", err)
		}
		return &next, pollInterval, nil
	case http.StatusUnauthorized, http.StatusForbidden:
		return nil, pollInterval, &refusedError{response.StatusCode}
	case http.StatusTooManyRequests:
		return nil, retryAfter(response.Header.Get("Retry-After")), errors.New("the server asked to slow down")
	}
	return nil, pollInterval, fmt.Errorf("the server answered %d", response.StatusCode)
}

func retryAfter(header string) time.Duration {
	seconds, err := strconv.Atoi(header)
	if err != nil || seconds <= 0 {
		return pollInterval
	}
	return min(time.Duration(seconds)*time.Second, maxBackoff)
}

func request(ctx context.Context, cfg config, method, path string, body io.Reader) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, cfg.Server+helperPath+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+cfg.Key)
	// Go's default User-Agent is what proxies such as Cloudflare challenge.
	req.Header.Set("User-Agent", "ais-matlab-helper/"+version)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return http.DefaultClient.Do(req)
}

// handle does one run and reports what became of it, to the browser that is
// waiting on the answer.
func handle(ctx context.Context, cfg config, next job) {
	fmt.Printf("%s: %s\n", next.Cell, next.Mode)
	err := open(ctx, cfg, next)
	message := ""
	if err != nil {
		message = err.Error()
		fmt.Fprintln(os.Stderr, "failed:", message)
	}
	report, _ := json.Marshal(map[string]any{"ok": err == nil, "message": message})
	reportCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	response, err := request(reportCtx, cfg, http.MethodPost, "jobs/"+url.PathEscape(next.ID)+"/done", strings.NewReader(string(report)))
	if err == nil {
		response.Body.Close()
	}
}

func open(ctx context.Context, cfg config, next job) error {
	runs, err := runsDir()
	if err != nil {
		return err
	}
	data, err := download(ctx, cfg, next)
	if err != nil {
		return err
	}
	folder := filepath.Join(runs, time.Now().Format("20060102-150405")+"-"+next.ID)
	if err := os.MkdirAll(folder, 0o700); err != nil {
		return err
	}
	root, err := unpack(data, folder)
	if err != nil {
		os.RemoveAll(folder)
		return err
	}
	matlab, err := findMatlab(cfg.Matlab, root)
	if err != nil {
		return err
	}
	fmt.Println("opening", matlab)
	prune(runs, keepRuns)
	return launch(matlab, root)
}

func download(ctx context.Context, cfg config, next job) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, downloadTimeout)
	defer cancel()
	response, err := request(ctx, cfg, http.MethodGet, "jobs/"+url.PathEscape(next.ID)+"/bundle", nil)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("the server answered %d for the images", response.StatusCode)
	}
	return io.ReadAll(io.LimitReader(response.Body, maxZipBytes))
}

func configPath() (string, error) {
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "ais-matlab-helper", "config.json"), nil
}

func loadConfig() (config, error) {
	var cfg config
	path, err := configPath()
	if err != nil {
		return cfg, err
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return cfg, errors.New("not connected yet: run  ais-matlab-helper connect <server url> <key>  with the line from Account in AIS Counter")
	}
	if err != nil {
		return cfg, err
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return cfg, fmt.Errorf("%s: %w", path, err)
	}
	return cfg, nil
}

// saveConfig keeps the key readable by you alone.
func saveConfig(cfg config) error {
	path, err := configPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		return err
	}
	return os.Chmod(path, 0o600)
}

func runsDir() (string, error) {
	dir, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "ais-matlab-helper", "runs"), nil
}
