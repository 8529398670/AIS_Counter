package main

import (
	"archive/zip"
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const maxZipBytes = 1 << 30

// allowed is every name a server's zip may hold (app/analysis/matlab_bundle.py).
// The helper runs what it unpacks, so anything else, such as a startup.m that
// MATLAB would run by itself, is refused rather than skipped.
var allowed = []*regexp.Regexp{
	regexp.MustCompile(`^[A-Za-z0-9_.-]+\.tif$`),
	regexp.MustCompile(`^[A-Za-z0-9_.-]+\.tif - Processed method 2\.5\.tif$`),
	regexp.MustCompile(`^(ais_auto|ais_auto_settings|ais_auto_replay|ais_replay_click|ais_replay_start)\.m$`),
	regexp.MustCompile(`^(run\.sh|run\.bat|matlab_path\.txt|README\.txt)$`),
}

func allowedName(name string) bool {
	for _, pattern := range allowed {
		if pattern.MatchString(name) {
			return true
		}
	}
	return false
}

// unpack writes the zip's one folder under dest and returns its path. Every
// entry is checked before anything is written.
func unpack(data []byte, dest string) (string, error) {
	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return "", fmt.Errorf("the server's zip could not be read: %w", err)
	}
	top := ""
	for _, entry := range archive.File {
		parts := strings.Split(entry.Name, "/")
		if len(parts) != 2 || parts[0] == "" || parts[0] == ".." || parts[0] == "." || strings.Contains(entry.Name, "\\") ||
			path.IsAbs(entry.Name) || !entry.Mode().IsRegular() || !allowedName(parts[1]) {
			return "", fmt.Errorf("refusing the server's zip: unexpected entry %q", entry.Name)
		}
		if top != "" && parts[0] != top {
			return "", fmt.Errorf("refusing the server's zip: more than one folder")
		}
		top = parts[0]
	}
	if top == "" {
		return "", errors.New("the server's zip is empty")
	}
	root := filepath.Join(dest, top)
	if err := os.MkdirAll(root, 0o700); err != nil {
		return "", err
	}
	for _, entry := range archive.File {
		if err := write(entry, filepath.Join(root, path.Base(entry.Name))); err != nil {
			return "", err
		}
	}
	return root, nil
}

func write(entry *zip.File, target string) error {
	source, err := entry.Open()
	if err != nil {
		return err
	}
	defer source.Close()
	// Nothing here is executed by mode: MATLAB reads the .m files, and the
	// scripts are never run (see launch).
	file, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = io.Copy(file, source)
	return err
}

// prune keeps the newest runs: names start with the time.
func prune(dir string, keep int) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			names = append(names, entry.Name())
		}
	}
	sort.Strings(names)
	for _, name := range names[:max(0, len(names)-keep)] {
		os.RemoveAll(filepath.Join(dir, name))
	}
}
