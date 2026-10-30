function probe_primitives(image_base, out_file)
% Dumps MATLAB's behaviour for every primitive the Python port re-implements,
% so tests/test_mlcompat.py can compare them one at a time.
rng(12345, 'twister');
P = struct();

% --- image front end: mat2gray, gaussian kernel, imfilter, masks ---------
pic = imread([image_base '.tif - Processed method 2.5.tif']);
Ch = pic(:,:,1);
P.pic = Ch;
Chais = mat2gray(Ch);
P.Chais = Chais;
h = fspecial('gaussian', [20 20], 2);
P.h = h;
S = imfilter(Chais, h);
P.Chais_smooth = S;
P.th_list = [0.01 0.0087 0.005 0.0123 0.002];
for k = 1:numel(P.th_list)
    bw = im2bw(S, P.th_list(k));
    o = imopen(bw, strel('square',3));
    c = imclose(o, strel('square',3));
    P.(sprintf('bw_%d',k)) = bw;
    P.(sprintf('open_%d',k)) = o;
    P.(sprintf('close_%d',k)) = c;
end
P.otsu = graythresh(S);
raw = imread([image_base '.tif']);
P.raw = raw;

% --- binary morphology on random masks (incl. borders) ------------------
for k = 1:20
    m = rand(60, 45) > (0.3 + 0.4*rand);
    P.(sprintf('morph_in_%d',k)) = m;
    P.(sprintf('morph_open_%d',k)) = imopen(m, strel('square',3));
    P.(sprintf('morph_close_%d',k)) = imclose(m, strel('square',3));
end

% --- method settings: the log kernel, other strel sizes (even ones too) ---
P.h_log = fspecial('log', [20 20], 2);
P.strel_ks = [1 2 4 5 7];
for k = P.strel_ks
    for j = 1:5
        m = P.(sprintf('morph_in_%d',j));
        P.(sprintf('open_k%d_%d',k,j)) = imopen(m, strel('square',k));
        P.(sprintf('close_k%d_%d',k,j)) = imclose(m, strel('square',k));
    end
end

% --- bwdist feature transform: random sparse images, many ties -----------
nb = 300;
P.bwd_n = nb;
for k = 1:nb
    sz = [randi([3 40]) randi([3 40])];
    m = false(sz);
    nf = randi([1 8]);
    m(randi(numel(m), nf, 1)) = true;
    if mod(k, 3) == 0   % symmetric patterns force exact ties
        r = randi(sz(1)); c = randi(sz(2)); d = randi(4);
        rr = [r-d r+d r r]; cc = [c c c-d c+d];
        ok = rr>=1 & rr<=sz(1) & cc>=1 & cc<=sz(2);
        m(sub2ind(sz, rr(ok), cc(ok))) = true;
    end
    [~, idx] = bwdist(m);
    P.(sprintf('bwd_in_%d',k)) = m;
    P.(sprintf('bwd_idx_%d',k)) = double(idx);
end

% --- thinning: LUTs and results on random blobs --------------------------
P.lutthin1 = double(images.internal.lutthin1());
P.lutthin2 = double(images.internal.lutthin2());
for k = 1:30
    sz = [randi([10 80]) randi([10 80])];
    m = imfilter(rand(sz), fspecial('gaussian', 7, 2), 'replicate') > 0.5;
    P.(sprintf('thin_in_%d',k)) = m;
    P.(sprintf('thin_out_%d',k)) = bwmorph(m, 'thin', Inf);
end

% --- colon and csaps -----------------------------------------------------
Ns = [2 3 4 5 7 10 19 20 21 50 99 100 101 150 237 300 301];
P.Ns = Ns;
for k = 1:numel(Ns)
    N = Ns(k);
    ts = [[1: 0.1: N], N];
    P.(sprintf('ts_%d',k)) = ts;
    xy = cumsum(randi([-1 1], 2, N), 2) + [500; 300];
    P.(sprintf('xy_%d',k)) = xy;
    P.(sprintf('xysm_%d',k)) = csaps(1:N, double(xy), 0.3, ts);
end

% --- comma-list assignment from a cell with several indices -------------
C = {[1 2 3], [4 5 6], [7 8 9]};
longline = [2 3];
X = C{longline};
P.comma_first = X;

% --- num2str(x,6) formatting --------------------------------------------
P.fmt_vals = [0 0.161 1.932 24.472 30.268 9.821 100.142 123.4567 0.0161 1e-5 1234.5678 -3.22];
P.fmt_strs = arrayfun(@(v) num2str(v, 6), P.fmt_vals, 'UniformOutput', false);

save(out_file, '-struct', 'P', '-v7');
end
