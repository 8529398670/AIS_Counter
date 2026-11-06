//go:build !windows

package main

import (
	"os/exec"
	"syscall"
)

// detach gives MATLAB its own session, so Ctrl-C here leaves it open.
func detach(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}
