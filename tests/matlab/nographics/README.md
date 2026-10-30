No-op stand-ins for the graphics functions `ais_auto.m` calls. `run_golden.m`
puts this folder first on the path so golden runs never open a figure. The
analysis never reads anything back from its plots.
