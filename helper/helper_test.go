package main

import (
	"archive/zip"
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func zipOf(t *testing.T, names ...string) []byte {
	t.Helper()
	var out bytes.Buffer
	archive := zip.NewWriter(&out)
	for _, name := range names {
		w, err := archive.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		w.Write([]byte("x"))
	}
	archive.Close()
	return out.Bytes()
}

func TestUnpackTakesARealBundle(t *testing.T) {
	dest := t.TempDir()
	root, err := unpack(zipOf(t,
		"c-matlab-replay/c.tif", "c-matlab-replay/c.tif - Processed method 2.5.tif",
		"c-matlab-replay/ais_auto_replay.m", "c-matlab-replay/ais_replay_click.m", "c-matlab-replay/ais_replay_start.m",
		"c-matlab-replay/run.sh", "c-matlab-replay/run.bat", "c-matlab-replay/matlab_path.txt", "c-matlab-replay/README.txt",
	), dest)
	if err != nil {
		t.Fatal(err)
	}
	if root != filepath.Join(dest, "c-matlab-replay") {
		t.Fatal(root)
	}
	if _, err := os.Stat(filepath.Join(root, "ais_replay_start.m")); err != nil {
		t.Fatal(err)
	}
}

func TestUnpackRefusesAnythingElse(t *testing.T) {
	for _, name := range []string{
		"../evil/run.sh", "/etc/run.sh", "a/../run.sh", "..\\run.sh", "a/b/run.sh", "run.sh",
		"a/startup.m", "a/finish.m", "a/evil.m", "a/evil.sh", "a/.bashrc", "a/x.tif.exe", "../c.tif", "./c.tif",
	} {
		dest := t.TempDir()
		if _, err := unpack(zipOf(t, name), dest); err == nil {
			t.Errorf("%q was accepted", name)
		}
		if entries, _ := os.ReadDir(dest); len(entries) != 0 {
			t.Errorf("%q wrote something before being refused", name)
		}
	}
}

func TestUnpackRefusesTwoFolders(t *testing.T) {
	if _, err := unpack(zipOf(t, "a/run.sh", "b/run.bat"), t.TempDir()); err == nil {
		t.Fatal("accepted")
	}
}

func fakeMatlab(t *testing.T, path string) string {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

func savedPath(t *testing.T, folder, path string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(folder, "matlab_path.txt"), []byte(path), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestThePathOnThisComputerWins(t *testing.T) {
	dir := t.TempDir()
	local := fakeMatlab(t, filepath.Join(dir, "mine", "my-matlab"))
	savedPath(t, dir, fakeMatlab(t, filepath.Join(dir, "account", "matlab")))
	found, err := findMatlab(local, dir)
	if err != nil || found != local {
		t.Fatal(found, err)
	}
}

func TestAMissingLocalPathIsAnErrorNotASurprise(t *testing.T) {
	if _, err := findMatlab("/nonexistent/matlab", t.TempDir()); err == nil {
		t.Fatal("expected an error")
	}
}

func TestTheAccountPathIsUsed(t *testing.T) {
	dir := t.TempDir()
	saved := fakeMatlab(t, filepath.Join(dir, "account", "matlab"))
	savedPath(t, dir, saved)
	found, err := findMatlab("", dir)
	if err != nil || found != saved {
		t.Fatal(found, err)
	}
}

func TestAnAccountFolderMeansItsBinMatlab(t *testing.T) {
	dir := t.TempDir()
	inner := fakeMatlab(t, filepath.Join(dir, "MATLAB_R2024b.app", "bin", binaryName()))
	savedPath(t, dir, filepath.Join(dir, "MATLAB_R2024b.app"))
	found, err := findMatlab("", dir)
	if err != nil || found != inner {
		t.Fatal(found, err)
	}
}

func TestTheServerCannotNameAnotherProgram(t *testing.T) {
	dir := t.TempDir()
	evil := fakeMatlab(t, filepath.Join(dir, "calc"))
	savedPath(t, dir, evil)
	found, _ := findMatlab("", dir)
	if found == evil {
		t.Fatal("ran a program the server named")
	}
}

func TestNewestIsTheLatestRelease(t *testing.T) {
	dir := t.TempDir()
	fakeMatlab(t, filepath.Join(dir, "R2024a", "bin", "matlab"))
	want := fakeMatlab(t, filepath.Join(dir, "R2024b", "bin", "matlab"))
	if got := newest([]string{filepath.Join(dir, "R*", "bin", "matlab")}); got != want {
		t.Fatal(got)
	}
}

func TestPlainHTTPIsForThisComputerOnly(t *testing.T) {
	for server, wantError := range map[string]bool{
		"https://ais.example.org":   false,
		"http://127.0.0.1:24005":    false,
		"http://localhost:24005":    false,
		"http://[::1]:24005":        false,
		"http://ais.example.org":    true,
		"http://192.168.1.5:24005":  true,
		"http://localhost.evil.org": true,
		"ftp://ais.example.org":     true,
		"ais.example.org":           true,
	} {
		if err := checkServer(server, false); (err != nil) != wantError {
			t.Errorf("%s: %v", server, err)
		}
	}
	if err := checkServer("http://192.168.1.5:24005", true); err != nil {
		t.Error(err)
	}
}

func server(t *testing.T, handler http.HandlerFunc) config {
	t.Helper()
	test := httptest.NewServer(handler)
	t.Cleanup(test.Close)
	return config{Server: test.URL, Key: "id.secret"}
}

func TestPollSendsTheKeyAndAName(t *testing.T) {
	cfg := server(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/ais/matlab/helper/next" || r.Header.Get("Authorization") != "Bearer id.secret" ||
			!strings.HasPrefix(r.Header.Get("User-Agent"), "ais-matlab-helper/") {
			t.Errorf("%s %v", r.URL.Path, r.Header)
		}
		w.Write([]byte(`{"id":"j1","mode":"replay","cell":"c"}`))
	})
	next, _, err := poll(context.Background(), cfg)
	if err != nil || next == nil || next.ID != "j1" {
		t.Fatal(next, err)
	}
}

func TestNoJobIsNotAnError(t *testing.T) {
	cfg := server(t, func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) })
	next, wait, err := poll(context.Background(), cfg)
	if err != nil || next != nil || wait != pollInterval {
		t.Fatal(next, wait, err)
	}
}

func TestARevokedKeyStopsTheHelper(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden} {
		cfg := server(t, func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(status) })
		cfg.Server = strings.Replace(cfg.Server, "localhost", "127.0.0.1", 1)
		done := make(chan error, 1)
		go func() { done <- serve(context.Background(), cfg) }()
		select {
		case err := <-done:
			if err == nil || !strings.Contains(err.Error(), "connect again") {
				t.Fatal(err)
			}
		case <-time.After(5 * time.Second):
			t.Fatal("kept polling a dead key")
		}
	}
}

func TestSlowDownIsHonoured(t *testing.T) {
	cfg := server(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "42")
		w.WriteHeader(http.StatusTooManyRequests)
	})
	_, wait, err := poll(context.Background(), cfg)
	var refused *refusedError
	if err == nil || errors.As(err, &refused) || wait != 42*time.Second {
		t.Fatal(wait, err)
	}
	if retryAfter("99999") != maxBackoff || retryAfter("soon") != pollInterval {
		t.Fatal("bad Retry-After handling")
	}
}

func TestConfigIsPrivate(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("no unix modes")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	if err := saveConfig(config{Server: "https://x", Key: "k"}); err != nil {
		t.Fatal(err)
	}
	path, _ := configPath()
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatal(info.Mode(), err)
	}
	cfg, err := loadConfig()
	if err != nil || cfg.Key != "k" {
		t.Fatal(cfg, err)
	}
}

func TestPruneKeepsTheNewest(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"20260101-a", "20260102-b", "20260103-c"} {
		os.Mkdir(filepath.Join(dir, name), 0o700)
	}
	prune(dir, 2)
	entries, _ := os.ReadDir(dir)
	if len(entries) != 2 || entries[0].Name() != "20260102-b" {
		t.Fatal(entries)
	}
}

// launch is only ever given a stub here, never a real MATLAB.
func TestLaunchPassesTheFolderThroughTheEnvironment(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the stub is a shell script")
	}
	dir := t.TempDir()
	stub := filepath.Join(dir, "matlab")
	os.WriteFile(stub, []byte("#!/bin/sh\n{ echo \"$AIS_REPLAY_DIR\"; printf '%s\\n' \"$@\"; } > ran.tmp && mv ran.tmp ran.txt\n"), 0o755)
	if err := launch(stub, dir); err != nil {
		t.Fatal(err)
	}
	want := dir + "\n-desktop\n-r\n" + launchLine + "\n"
	for range 200 {
		if got, err := os.ReadFile(filepath.Join(dir, "ran.txt")); err == nil {
			if string(got) != want {
				t.Fatalf("%q", got)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("the stub never ran")
}
