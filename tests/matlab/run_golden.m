function run_golden(jobs_file, out_dir)
% Runs the headless original on every job in jobs_file (JSON list of
% {id, base, clicks:[[x,y],...]}) and writes <id>_trace.mat, <id>_final.mat
% and <id>.json ({id, ok, error_id, error_msg, seconds}) into out_dir.
global AIS_CLICKS
here = fileparts(mfilename('fullpath'));
addpath(here, fullfile(here, 'build'));
% Graphics calls become no-ops (see nographics/README.md): no figure is ever
% opened, so nothing can crash when the batch session exits.
warning('off', 'MATLAB:dispatcher:nameConflict');
addpath(fullfile(here, 'nographics'), '-begin');
cleanup = onCleanup(@() rmpath(fullfile(here, 'nographics')));
if ~exist(out_dir, 'dir'), mkdir(out_dir); end
jobs = jsondecode(fileread(jobs_file));
if isstruct(jobs), jobs = num2cell(jobs); end
for k = 1:numel(jobs)
    job = jobs{k};
    stem = fullfile(out_dir, job.id);
    if exist([stem '.json'], 'file'), continue; end
    AIS_CLICKS = reshape(job.clicks, [], 2);
    setappdata(0, 'ais_dump_trace', [stem '_trace.mat']);
    setappdata(0, 'ais_dump_final', [stem '_final.mat']);
    setappdata(0, 'ais_xy_prefix', stem);
    r = struct('id', job.id, 'ok', true, 'error_id', '', 'error_msg', '', 'error_line', 0, 'seconds', 0);
    t0 = tic;
    try
        evalc('ais_auto_headless(job.base, 0.01, ''gaussian'', 0);');
    catch err
        r.ok = false; r.error_id = err.identifier; r.error_msg = err.message;
        hit = err.stack(strcmp({err.stack.name}, 'ais_auto_headless'));
        if ~isempty(hit), r.error_line = hit(1).line; end
    end
    r.seconds = toc(t0);
    fid = fopen([stem '.json'], 'w'); fprintf(fid, '%s', jsonencode(r)); fclose(fid);
    if ~isempty(get(groot, 'Children')), error('run_golden:figure', 'a figure was opened'); end
    fprintf('%d/%d %s ok=%d %.1fs %s\n', k, numel(jobs), job.id, r.ok, r.seconds, r.error_msg);
end
end
