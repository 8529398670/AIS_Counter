function [x, y] = next_click()
% Stand-in for ginput(1): pops the next queued click (MATLAB axes coordinates,
% pixel centres at integers). With one queued click the last one repeats, which
% is "the user clicked the same spot again" for the re-threshold iteration.
global AIS_CLICKS
x = AIS_CLICKS(1,1);
y = AIS_CLICKS(1,2);
if size(AIS_CLICKS,1) > 1
    AIS_CLICKS(1,:) = [];
end
end
