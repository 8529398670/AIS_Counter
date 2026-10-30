function varargout = hold(varargin)
% No-op stand-in for the built-in hold, on the path only for golden runs.
% ais_auto.m plots ~10 figures per click; even invisible ones start MATLAB's
% web figure renderer, which crashes (with a dialog) when the batch exits.
% None of the plotting affects the analysis.
varargout = cell(1, nargout);
end
