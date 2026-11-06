package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
)

// launchLine is LAUNCH in app/analysis/matlab_bundle.py. The folder comes in
// through the environment, so no path is ever quoted into MATLAB code.
const launchLine = "cd(getenv('AIS_REPLAY_DIR')); ais_replay_start"

func binaryName() string {
	if runtime.GOOS == "windows" {
		return "matlab.exe"
	}
	return "matlab"
}

// usable returns the MATLAB a path means: the file, or for a folder (a
// MATLAB_R2024b.app or an install root) the bin/matlab inside it.
func usable(path string) (string, bool) {
	info, err := os.Stat(path)
	if err != nil {
		return "", false
	}
	if info.IsDir() {
		inner := filepath.Join(path, "bin", binaryName())
		if inner, ok := usable(inner); ok {
			return inner, true
		}
		return "", false
	}
	if runtime.GOOS != "windows" && info.Mode()&0o111 == 0 {
		return "", false
	}
	return path, true
}

// trustedName is the check on a path that came from the server rather than from
// this computer: it may only choose among MATLABs, never name another program.
func trustedName(path string) bool {
	base := strings.ToLower(filepath.Base(strings.ReplaceAll(path, "\\", "/")))
	if base == "matlab" || base == "matlab.exe" {
		return true
	}
	if info, err := os.Stat(path); err == nil && info.IsDir() {
		_, ok := usable(path)
		return ok
	}
	return false
}

// findMatlab: the path set on this computer, then the one on your account (from
// the zip), then the newest install, then the PATH.
func findMatlab(local, folder string) (string, error) {
	if local != "" {
		if found, ok := usable(local); ok {
			return found, nil
		}
		return "", fmt.Errorf("the MATLAB set for this helper is not there: %s", local)
	}
	if saved, err := os.ReadFile(filepath.Join(folder, "matlab_path.txt")); err == nil {
		path := strings.TrimSpace(string(saved))
		if path != "" && trustedName(path) {
			if found, ok := usable(path); ok {
				return found, nil
			}
		}
	}
	if found := newest(installs()); found != "" {
		return found, nil
	}
	if found, err := exec.LookPath("matlab"); err == nil {
		return found, nil
	}
	return "", errors.New("MATLAB was not found on your computer: save its path under Account in AIS Counter")
}

func installs() []string {
	switch runtime.GOOS {
	case "darwin":
		return []string{"/Applications/MATLAB_R*.app/bin/matlab"}
	case "windows":
		return []string{filepath.Join(os.Getenv("ProgramFiles"), "MATLAB", "R*", "bin", "matlab.exe")}
	}
	home, _ := os.UserHomeDir()
	return []string{"/usr/local/MATLAB/R*/bin/matlab", "/opt/MATLAB/R*/bin/matlab", filepath.Join(home, "MATLAB", "R*", "bin", "matlab")}
}

// newest sorts by name, which is by release: R2024a < R2024b < R2025a.
func newest(patterns []string) string {
	var found []string
	for _, pattern := range patterns {
		matches, _ := filepath.Glob(pattern)
		for _, match := range matches {
			if path, ok := usable(match); ok {
				found = append(found, path)
			}
		}
	}
	if len(found) == 0 {
		return ""
	}
	sort.Strings(found)
	return found[len(found)-1]
}

func launchArgs() []string {
	// -desktop: a MATLAB with no terminal otherwise quits when the run returns,
	// taking the result figures with it. On Windows the desktop is the default.
	if runtime.GOOS == "windows" {
		return []string{"-r", launchLine}
	}
	return []string{"-desktop", "-r", launchLine}
}

// launch starts MATLAB itself, never the zip's scripts, so that it outlives this
// helper. The folder arrives as AIS_REPLAY_DIR.
func launch(matlab, folder string) error {
	logFile, err := os.Create(filepath.Join(folder, "matlab_launch.log"))
	if err != nil {
		return err
	}
	defer logFile.Close()
	command := exec.Command(matlab, launchArgs()...)
	command.Dir = folder
	command.Env = append(os.Environ(), "AIS_REPLAY_DIR="+folder)
	command.Stdout, command.Stderr = logFile, logFile
	detach(command)
	if err := command.Start(); err != nil {
		return fmt.Errorf("could not start MATLAB: %w", err)
	}
	go command.Wait() // or each MATLAB closed leaves a zombie behind
	return nil
}
