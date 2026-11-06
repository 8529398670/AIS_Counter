//go:build windows

package main

import (
	"os/exec"
	"syscall"
)

const createNewProcessGroup = 0x00000200

// detach keeps Ctrl-C here from reaching MATLAB.
func detach(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNewProcessGroup}
}
