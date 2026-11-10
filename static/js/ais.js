// The Process screen: open a folder of TIFF pairs (or lone TIFFs, or .czi
// files: CZI mode), click near an AIS, see the original ais_auto.m's trace and
// length, accept or reject it.
//
// The analysis is all server-side (app/analysis/). Each opened folder becomes
// a batch on the server (app/models/ais.py), shared with every signed-in
// user: its images, which are done, and the accepted AIS. The URL names the
// batch and image (#ais/<id>-<folder>/<image>), so a link opens the same
// image for anyone. ais_images.js holds the Images, Open path and Batches
// dialogs, ais_export.js the CSV and ZIP exports, ais_auto.js auto mode.
//
// A folder picked in the browser is hashed here first (sha-256, the id the
// server stores files under), so the batch, its duplicates and its link exist
// at once; the files then upload in the background. An Open-path folder is
// read by the server itself.
//
// Coordinates sent to and received from the server are MATLAB axes
// coordinates: x = column, y = row, pixel centres at 1..n. On the canvas a
// pixel (x, y) covers [x-1, x) x [y-1, y) in image units.
// The Soma button's outlines (a .czi's cell bodies, from its AMCA channel).
const SOMA_COLOUR = "rgba(255, 140, 40, 0.85)";
// The part of a trace at the slice shown.
const SLICE_COLOUR = "rgba(255, 60, 255, 1)";

const Ais = {
  processedSuffix: ".tif - Processed method 2.5.tif",
  concurrency: 4,        // files hashed, uploaded or exported at once
  imageCache: new Map(),   // view.png URL -> { promise, img, decoded, bitmap, gamma }: the last few previews, decoded
  imageCacheSize: 12,    // the image on screen, the 6 preloaded around it, and a few just left
  preloadAtOnce: 2,      // previews downloaded side by side ahead of the arrow keys
  stepDelay: 60,        // ms an arrow-key step waits before downloading an image not in the cache
  direction: 1,          // the way the arrow keys last stepped, which preload looks first
  legacyResultsKey: "ais-results",
  viewKey: "ais-view",
  lastKey: "ais-last",   // the last batch and image, for a bare #ais or /
  focusKey: "ais-focus",
  layersKey: "ais-layers-hidden",   // overlays switched off under Appearance
  noteKey: "ais-note-hidden",   // the batch whose single-image note was closed
  // An image: { key, cell, dir, dup_of?, add_id?, original_key?, included,
  // files: { processed?, raw?, czi? } } with a file { name, rel, sha, size,
  // stored, modified?, created?, original?, path?, file? } -- `file` only in
  // the browser that picked it, `path` only for Open path, `original` (the
  // name before it was blinded) only for admins. included: stepped through
  // here -- not left out for the team (batch.excluded), and one of mine when
  // I have images assigned.
  images: [],
  batch: null,           // the server's batch record
  openFresh: null,       // a batch id the Batches screen just created: opens with the Images dialog
  following: null,       // the hash followUrl is opening
  me: null,
  local: { enabled: false , platform: "" , matlab: false },
  index: -1,
  bitmap: null,          // the current image, brightness applied, as a canvas
  source: null,          // its decoded <img>
  // The views the bottom-left buttons offer besides the processed image: a
  // .czi's channels, or a TIFF pair's raw file. { list: [{ key, name, label,
  // color, src, img? }], on: Set of keys } -- none on shows the processed
  // image. viewWanted: the names last switched on, kept for the next image.
  views: null,
  sliceZ: null,     // the z of the slice shown; null on the projection
  viewWanted: [],
  // The Soma button (a .czi): its soma outlines drawn over the image, fetched
  // once per image; switched on, it stays on for the next image.
  showSomata: false,
  somata: null,
  viewsOpen: false,      // the view buttons spread out along the top, or folded into one
  view: { scale: 1 , ox: 0 , oy: 0 },
  locked: false,         // pan and zoom frozen, the same view on every image
  focus: false,          // focus mode: only the image, navigation and result
  result: null,          // the last trace answer from the server
  lastBody: null,        // the clicks that produced it, for nudging
  queuedBody: null,      // a nudge that arrived while a trace was running
  firstClick: null,      // two-click mode: waiting for the second click
  batchRows: [],         // accepted AIS of the open batch
  measurements: [],      // its recorded lines (ais_measure.js)
  allMeasurements: null, // every batch's, once the scope "all" has asked for them
  // What a click on the image does: "trace" a new AIS, "edit" one (its start
  // walked or clicked anew, Enter keeps it) or "delete" one. A target is an
  // auto candidate or a saved row: { kind: "candidate" | "row", item }.
  tool: "trace",
  editing: null,         // the target being edited
  hover: null,           // the target under the pointer (Edit / Delete)
  allRows: null,         // every batch's, loaded when the table shows all
  // Undo / redo of the saved rows: each step { kind: "add" | "edit" |
  // "delete", ref, before, after }. A ref is one row through deletes and
  // re-adds (which give it a new id), so older steps still find it.
  undoStack: [],
  redoStack: [],
  historyBatch: null,    // the batch the stacks belong to
  refs: new Map(),       // row id -> its ref
  busy: false,
  historyBusy: false,    // an undo / redo is on its way to the server

  init( me ) {
    this.me = me || null;
    this.canvas = Dom.get( "ais-canvas" );
    this.ctx = this.canvas.getContext( "2d" );
    this.loadView();

    Dom.get( "ais-image" ).addEventListener( "change" , ( e ) => this.show( Number( e.target.value ) ) );
    Dom.get( "ais-prev" ).addEventListener( "click" , () => this.step( -1 ) );
    Dom.get( "ais-next" ).addEventListener( "click" , () => this.step( 1 ) );
    Dom.get( "ais-gamma" ).addEventListener( "input" , () => { this.buildBitmap(); this.draw(); } );
    Dom.get( "ais-gamma-reset" ).addEventListener( "click" , () => {
      const gamma = Dom.get( "ais-gamma" );
      gamma.value = "1";
      gamma.dispatchEvent( new Event( "input" ) );
    } );
    Dom.get( "ais-channels" ).addEventListener( "click" , ( e ) => {
      if ( e.target.closest( "#ais-channels-toggle" ) ) {
        this.viewsOpen = !this.viewsOpen;
        this.renderViews();
        return;
      }
      const button = e.target.closest( "[data-view]" );
      if ( button ) this.toggleView( button.dataset.view );
    } );
    // Leaving the corner folds the row away again.
    Dom.get( "ais-channels" ).addEventListener( "mouseleave" , () => {
      if ( !this.viewsOpen ) return;
      this.viewsOpen = false;
      this.renderViews();
    } );
    this.loadLayers();
    Dom.all( "[data-layer]" ).forEach( ( box ) => box.addEventListener( "change" , () => { this.saveLayers(); this.draw(); } ) );
    Dom.get( "ais-accept" ).addEventListener( "click" , () => this.accept() );
    Dom.all( "[data-tool]" ).forEach( ( button ) => button.addEventListener( "click" , () => this.setTool( button.dataset.tool ) ) );
    Dom.get( "ais-reject" ).addEventListener( "click" , () => this.reject() );
    Dom.get( "ais-replay" ).addEventListener( "click" , () => this.replayInMatlab() );
    Dom.get( "ais-replay-download" ).addEventListener( "click" , () => this.downloadReplay() );
    Dom.get( "ais-table-scope" ).addEventListener( "change" , () => this.loadTable() );
    // A changed setting (on the Settings screen) drops a half-done two-click.
    // A method setting starts the click over; a general one (thickness, minimum
    // length) only redraws, and the minimum applies from the next trace.
    let method = Settings.methodState();
    Settings.onChange( () => {
      if ( Settings.methodState() !== method ) { this.firstClick = null; this.status( "" ); }
      method = Settings.methodState();
      this.draw();
    } );

    Dom.get( "ais-file-open" ).addEventListener( "click" , () => this.openCurrent() );
    Dom.get( "ais-file-reveal" ).addEventListener( "click" , () => this.revealCurrent() );
    Dom.get( "ais-file-copy" ).addEventListener( "click" , () => this.copyCurrent() );
    Dom.get( "ais-file-link" ).addEventListener( "click" , () => this.copyText( window.location.href ) );
    Dom.get( "ais-file-done" ).addEventListener( "click" , () => this.toggleDone() );
    Dom.all( "[data-matlab]" , Dom.get( "ais-current" ) ).forEach( ( item ) => item.addEventListener( "click" ,
      () => this.verifyInMatlab( this.images[ this.index ] , item.dataset.matlab ) ) );

    Dom.get( "ais-zoom-in" ).addEventListener( "click" , () => this.zoomBy( 1.25 ) );
    Dom.get( "ais-zoom-out" ).addEventListener( "click" , () => this.zoomBy( 0.8 ) );
    Dom.get( "ais-zoom-level" ).addEventListener( "click" , () => this.zoomTo( 1 ) );
    Dom.get( "ais-view-reset" ).addEventListener( "click" , () => this.resetView() );
    const zSlider = Dom.get( "ais-z-slider" );
    zSlider.addEventListener( "input" , () => this.setSlice( Number( zSlider.value ) ) );
    // Focus would stay on it, and it would keep the keyboard shortcuts.
    zSlider.addEventListener( "change" , () => zSlider.blur() );
    Dom.get( "ais-undo" ).addEventListener( "click" , () => this.undo() );
    Dom.get( "ais-redo" ).addEventListener( "click" , () => this.redo() );
    Dom.get( "ais-view-lock" ).addEventListener( "click" , () => this.setLocked( !this.locked ) );
    Dom.get( "ais-focus" ).addEventListener( "click" , () => this.setFocus( !this.focus ) );
    Dom.get( "ais-status-close" ).addEventListener( "click" , () => this.hideNote() );
    // Esc out of the browser's full screen leaves focus mode too.
    document.addEventListener( "fullscreenchange" , () => {
      if ( !document.fullscreenElement && this.focus ) this.setFocus( false );
    } );

    this.bindCanvas();
    document.addEventListener( "keydown" , ( e ) => this.onKey( e ) );
    // The stage has no size while its view is hidden, so size the canvas
    // whenever the stage itself changes size, including when it first shows.
    new ResizeObserver( () => this.resize() ).observe( Dom.get( "ais-stage" ) );
    // In focus mode the stage runs to the bottom of the window, so it grows
    // back whatever the toolbar or file header give up (a shorter file name,
    // a narrower window).
    const around = new ResizeObserver( () => this.fitStage() );
    [ Dom.get( "ais-current" ) , document.querySelector( ".ais-toolbar" ) ]
      .forEach( ( element ) => around.observe( element ) );
    window.addEventListener( "resize" , () => this.fitStage() );
    window.addEventListener( "hashchange" , () => this.followUrl() );
    window.addEventListener( "popstate" , () => this.followUrl() );
    AisImages.init();
    AisAssign.init();
    AisExport.init();
    AisAuto.init();
    AisMeasure.init();
    this.renderPicker();
    this.renderTable();
    this.renderViewTools();
    this.renderTools();
    this.loadFocus();
    this.resize();
    this.loadLocal();
    // Whether this person's MATLAB helper is running changes while the page is
    // open, and the MATLAB buttons follow it.
    window.setInterval( () => {
      if ( this.local.helper_enabled && !document.hidden ) this.loadLocal();
    } , 10000 );
    this.importLegacy().finally( () => this.followUrl() );
  },

  async loadLocal() {
    const before = this.localLoaded ? this.canMatlab() : null;
    try {
      this.local = await Api.request( "/api/ais/local/status" );
    } catch ( error ) {
      this.local = { enabled: false , platform: "" , matlab: false , helper: false , helper_enabled: false };
    }
    this.localLoaded = true;
    MatlabAccount.render();
    if ( before === this.canMatlab() ) return;
    this.renderCurrent();
    this.renderResult( Boolean( this.firstClick ) );
    if ( before !== null ) AisImages.render();
  },

  // MATLAB is reachable: this person's helper, or this machine's own.
  canMatlab() {
    return Boolean( this.local.matlab || this.local.helper );
  },

  // Accepted AIS from before results lived on the server (this browser's
  // localStorage) move there once, as a batch of their own.
  async importLegacy() {
    let rows = [];
    try {
      rows = JSON.parse( window.localStorage.getItem( this.legacyResultsKey ) || "[]" );
    } catch ( error ) {
      rows = [];
    }
    if ( !Array.isArray( rows ) || !rows.length ) return;
    try {
      await Api.post( "/api/ais/results/import" , { name: I18n.get( "ais.imported_batch" ) || "Imported from browser" , rows: rows } );
      window.localStorage.removeItem( this.legacyResultsKey );
      window.localStorage.removeItem( "ais-batches" );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // --- the URL: #ais/<batch id>-<folder>/<image key> --------------------------

  urlFor( batch , entry ) {
    let hash = "#ais";
    if ( batch ) hash += "/" + batch.id + "-" + encodeURIComponent( batch.name );
    if ( batch && entry ) hash += "/" + encodeURIComponent( entry.key );
    return hash;
  },

  parseUrl() {
    const parts = window.location.hash.replace( /^#/ , "" ).split( "/" );
    if ( parts[ 0 ] !== "ais" || !parts[ 1 ] ) return null;
    const id = parseInt( parts[ 1 ] , 10 );
    if ( !( id > 0 ) ) return null;
    let key = null;
    try {
      key = parts[ 2 ] ? decodeURIComponent( parts[ 2 ] ) : null;
    } catch ( error ) {
      key = null;
    }
    return { id: id , key: key };
  },

  setUrl( push ) {
    const hash = this.urlFor( this.batch , this.images[ this.index ] );
    if ( this.batch ) {
      try {
        window.localStorage.setItem( this.lastKey , hash );
      } catch ( error ) { /* storage blocked: a reload keeps only the URL */ }
    }
    if ( window.location.hash === hash ) return;
    if ( push ) window.history.pushState( null , "" , hash );
    else window.history.replaceState( null , "" , hash );
  },

  // A pasted link, back / forward, or the first load: open what the URL names.
  // A bare #ais (or /) goes back to the open batch, or the last one seen.
  // One hash change fires both hashchange and popstate: followed once.
  async followUrl() {
    const hash = window.location.hash;
    if ( this.following === hash ) return;
    this.following = hash;
    try {
      await this.followUrlNow();
    } finally {
      if ( this.following === hash ) this.following = null;
    }
  },

  async followUrlNow() {
    if ( Nav.current() !== "ais" ) {
      if ( this.focus ) this.setFocus( false );
      return;
    }
    let want = this.parseUrl();
    let remembered = false;
    if ( !want ) {
      if ( this.batch && !this.stale ) { this.setUrl( false ); return; }
      if ( this.batch ) want = { id: this.batch.id , key: null };
    }
    if ( !want ) {
      let last = null;
      try {
        last = window.localStorage.getItem( this.lastKey );
      } catch ( error ) { /* storage blocked */ }
      if ( !last ) return;
      window.history.replaceState( null , "" , last );
      want = this.parseUrl();
      if ( !want ) return;
      remembered = true;
    }
    if ( this.batch && this.batch.id === want.id && !this.stale ) {
      const i = this.images.findIndex( ( entry ) => entry.key === want.key );
      if ( i >= 0 && i !== this.index ) {
        if ( !this.images[ i ].included ) { this.images[ i ].included = true; this.renderPicker(); }
        this.show( i );
      }
      return;
    }
    // Images added on the Batches screen: reload, keeping the files this
    // browser still has to upload.
    let carried = null;
    if ( this.batch && this.batch.id === want.id && this.stale ) {
      carried = new Map();
      this.images.forEach( ( entry ) => this.parts( entry ).forEach( ( f ) => { if ( f.file ) carried.set( f.sha , f.file ); } ) );
      if ( !want.key && this.images[ this.index ] ) want.key = this.images[ this.index ].key;
    }
    this.stale = false;
    try {
      const batch = await Api.request( "/api/ais/batches/" + want.id );
      // Just created with its images on the Batches screen: opens like Open
      // folder does, with the Images dialog.
      const fresh = this.openFresh === want.id;
      this.openFresh = null;
      await this.loadBatch( batch , carried , { key: want.key , fresh: fresh } );
    } catch ( error ) {
      // A remembered batch that has since been deleted is just forgotten.
      if ( remembered && error.status === 404 ) this.forgetLast();
      else App.showError( error.status === 404 ? I18n.get( "ais.no_batch" ) : error.message );
    }
  },

  forgetLast() {
    try {
      window.localStorage.removeItem( this.lastKey );
    } catch ( error ) { /* storage blocked */ }
    window.history.replaceState( null , "" , "#ais" );
  },

  // --- opening a batch -----------------------------------------------------

  // Picked in the browser: the images (TIFF or .czi) hashed, as a batch is
  // created or added to from names and hashes alone. onProgress(done, total)
  // follows the reading. null when none of the files is an image. bySha
  // finds each File again: the server may have blinded its name. A folder
  // blinded by RandomNames.bat brings its __Translation.txt along:
  // translations, [{ dir , text }] with dir its folder as an image's dir.
  async hashFiles( fileList , onProgress ) {
    const all = Array.from( fileList );
    const files = all.filter( ( f ) => /\.(tiff?|czi)$/i.test( f.name ) && !f.name.startsWith( "." ) );
    if ( !files.length ) return null;
    const rel = files[ 0 ].webkitRelativePath || "";
    const root = rel.includes( "/" ) ? rel.split( "/" )[ 0 ] : "";
    const translations = await Promise.all( all.filter( ( f ) => /^__Translation.*\.txt$/i.test( f.name ) ).map( async ( f ) => {
      const parts = ( f.webkitRelativePath || f.name ).split( "/" );
      return { dir: parts.slice( 1 , -1 ).join( "/" ) , text: await f.text() };
    } ) );
    const described = new Array( files.length );
    const bySha = new Map();
    let done = 0;
    // A few at a time: reading one file while another hashes.
    await this.pool( files , this.concurrency , async ( f , i ) => {
      const digest = await crypto.subtle.digest( "SHA-256" , await f.arrayBuffer() );
      const sha = Array.from( new Uint8Array( digest ) , ( b ) => b.toString( 16 ).padStart( 2 , "0" ) ).join( "" );
      const fileRel = f.webkitRelativePath || f.name;
      described[ i ] = { name: f.name , rel: fileRel , sha: sha , size: f.size };
      if ( f.lastModified ) described[ i ].modified = new Date( f.lastModified ).toISOString();
      bySha.set( sha , f );
      done += 1;
      onProgress( done , files.length );
    } );
    return { name: root || I18n.get( "ais.loose_files" ) || "Files" , files: described , bySha: bySha , translations: translations };
  },

  // Open folder / Open files: hash every image, create the batch from names
  // and hashes, then upload in the background.
  async openFiles( fileList ) {
    try {
      const picked = await this.hashFiles( fileList , ( done , total ) =>
        this.status( I18n.get( "ais.reading" ).replace( "{done}" , done ).replace( "{total}" , total ) ) );
      if ( !picked ) {
        App.showError( I18n.get( "ais.no_tiffs" ) );
        return;
      }
      const batch = await Api.post( "/api/ais/batches/upload" , { name: picked.name , files: picked.files ,
        randomize: Batches.randomize() , translations: picked.translations } );
      this.status( "" );
      Dom.toast( I18n.get( "batches.created" ).replace( "{name}" , batch.name ) );
      await this.loadBatch( batch , picked.bySha , { fresh: true } );
    } catch ( error ) {
      this.status( "" );
      App.showError( error.message );
    }
  },

  // Read by the server (Open path).
  async openPath( folder ) {
    try {
      const stack = await Batches.askStackAt( folder );
      if ( stack === false ) return;
      this.status( I18n.get( "ais.reading_path" ) );
      const batch = await Api.post( "/api/ais/batches/path" , Object.assign( { path: folder , randomize: Batches.randomize() } , stack ? { stack: stack } : {} ) );
      this.status( "" );
      await this.loadBatch( batch , null , { fresh: true } );
    } catch ( error ) {
      this.status( "" );
      App.showError( error.message );
    }
  },

  // Show a server batch. bySha maps a file's sha-256 to the File picked in
  // this browser (only right after Open folder / Open files). options.key
  // opens that image; options.fresh opens the Images dialog.
  async loadBatch( batch , bySha , options ) {
    const opts = options || {};
    AisAuto.reset();
    this.batch = batch;
    // A newly opened set of images shows the single-image note again.
    if ( opts.fresh ) {
      try {
        window.localStorage.removeItem( this.noteKey );
      } catch ( error ) { /* storage blocked */ }
    }
    this.images = batch.images.map( ( image ) => {
      const files = {};
      const picked = ( f ) => Object.assign( {} , f , { file: bySha ? bySha.get( f.sha ) || null : null } );
      Object.entries( image.files ).forEach( ( [ role , f ] ) => {
        files[ role ] = picked( f );
        if ( f.slices ) files[ role ].slices = f.slices.map( picked );
      } );
      return { key: image.key , cell: image.cell , dir: image.dir , dup_of: image.dup_of , add_id: image.add_id ,
        original_key: image.original_key , z_stack: image.z_stack , files: files , included: false };
    } );
    this.applyInclusion();
    this.index = -1;
    this.source = null;
    this.bitmap = null;
    this.reject();
    Dom.get( "ais-table-scope" ).value = "image";
    this.allRows = null;
    this.allMeasurements = null;
    await this.loadBatchRows();
    this.renderPicker();
    this.draw();
    let start = opts.key ? this.images.findIndex( ( entry ) => entry.key === opts.key ) : -1;
    if ( start >= 0 && !this.images[ start ].included ) {
      this.images[ start ].included = true;
      this.renderPicker();
    }
    if ( start < 0 ) {
      const shown = this.included();
      start = shown.find( ( i ) => !this.isComplete( this.images[ i ] ) ) ?? shown[ 0 ] ?? -1;
    }
    if ( start >= 0 ) this.show( start , true );
    else this.renderCurrent();
    if ( opts.fresh ) AisImages.open();
    this.uploadAll();
  },

  // --- assignments (an admin's split of the batch, app/models/ais.py) ------

  assigneeOf( entry ) {
    const assignment = this.batch && this.batch.assignment;
    const id = assignment ? assignment.images[ entry.key ] : null;
    return id == null ? null : id;
  },

  assigneeName( id ) {
    return ( this.batch && this.batch.assignee_names && this.batch.assignee_names[ String( id ) ] ) || "";
  },

  // The keys of the images assigned to whoever is signed in, or null.
  myKeys() {
    const assignment = this.batch && this.batch.assignment;
    if ( !assignment || !this.me ) return null;
    const keys = Object.keys( assignment.images ).filter( ( k ) => assignment.images[ k ] === this.me.id );
    return keys.length ? new Set( keys ) : null;
  },

  // The open batch was (re)assigned: take the new split, and if it gives
  // this person images, step through exactly those.
  applyAssignment( batch ) {
    this.batch.assignment = batch.assignment || null;
    this.batch.assignee_names = batch.assignee_names || {};
    this.applyInclusion();
    this.inclusionChanged( this.index );
    this.renderCurrent();
  },

  // The Batches screen changed a batch: a new name shows at once; added
  // images load when the Process screen shows it again.
  batchChanged( batch , added ) {
    if ( !this.batch || this.batch.id !== batch.id ) return;
    this.batch.name = batch.name;
    if ( batch.excluded ) {
      this.batch.excluded = batch.excluded;
      if ( !added ) {
        this.applyInclusion();
        this.inclusionChanged( this.index );
      }
    }
    if ( added ) this.stale = true;
    this.renderCurrent();
  },

  // Back to no batch (the open one was deleted).
  closeBatch() {
    AisAuto.reset();
    this.uploadToken = null;
    this.batch = null;
    this.images = [];
    this.batchRows = [];
    this.measurements = [];
    this.index = -1;
    this.source = null;
    this.bitmap = null;
    this.reject();
    Dom.show( Dom.get( "ais-empty" ) , true );
    Dom.text( Dom.get( "ais-upload-status" ) , "" );
    this.forgetLast();
    this.renderPicker();
    this.renderTable();
    this.draw();
  },

  // Which images to step through: those the team has not left out
  // (batch.excluded, set in the Images dialog), and of those only mine when
  // I have images assigned.
  applyInclusion() {
    const excluded = new Set( ( this.batch && this.batch.excluded ) || [] );
    const mine = this.myKeys();
    this.images.forEach( ( entry ) => { entry.included = !excluded.has( entry.key ) && ( !mine || mine.has( entry.key ) ); } );
  },

  // The Images dialog changed what the team leaves out of this batch.
  excludedChanged( excluded , prefer ) {
    if ( !this.batch ) return;
    this.batch.excluded = excluded;
    this.applyInclusion();
    if ( prefer != null && this.images[ prefer ] ) this.images[ prefer ].included = true;
    this.inclusionChanged( prefer != null ? prefer : this.index );
    this.uploadAll();
  },

  // The file that is thresholded and traced, and whether a separate raw
  // image exists to read the profile from. A .czi is both: the server traces
  // a processed version of its AIS channel and profiles the channel itself.
  traced( entry ) {
    if ( entry.files.stack ) return "stack";
    if ( entry.files.czi ) return "czi";
    return entry.files.processed ? "processed" : "raw";
  },

  // What a file name must look like to be a slice of a Z-stack: the same as
  // app/analysis/zstack.py SLICE_RE, which decides.
  stackRe: /^(.+?)_z([0-9]{1,4})(c[0-9+]+)?\.tiff?$/i,

  // The files of an image that are really files. A Z-stack has one that
  // stands for its slices, with a sha nothing can upload or download.
  parts( entry ) {
    return Object.values( entry.files ).flatMap( ( f ) => f.slices || [ f ] );
  },

  // µm per pixel on entry: a Z-stack came with its own.
  pixconvFor( entry ) {
    return entry && entry.z_stack ? entry.z_stack.pixel_um : Settings.pixconv();
  },

  // What the trace and detect bodies add for a Z-stack.
  zBody( entry ) {
    return entry.files.stack ? { z_method: Settings.zMethod() } : {};
  },

  sha( entry , role ) {
    const f = entry.files[ role || this.traced( entry ) ];
    return f ? f.sha : null;
  },

  kind( entry ) {
    if ( entry.files.stack ) return "stack";
    if ( entry.files.czi ) return "czi";
    if ( entry.files.processed && entry.files.raw ) return "pair";
    return entry.files.processed ? "processed only" : "raw only";
  },

  // Both the traced and the profiled image are there: a pair, or a .czi.
  whole( entry ) {
    const kind = this.kind( entry );
    return kind === "pair" || kind === "czi" || kind === "stack";
  },

  // Indices of the images to step through, in list order.
  included() {
    return this.images.map( ( entry , i ) => ( entry.included ? i : -1 ) ).filter( ( i ) => i >= 0 );
  },

  // --- progress (shared: accepted AIS and done marks live on the server) -------

  acceptedCount( entry ) {
    return this.batchRows.filter( ( r ) => r.image === entry.key ).length;
  },

  isMarkedDone( entry ) {
    return Boolean( this.batch ) && this.batch.skipped.includes( entry.key );
  },

  isComplete( entry ) {
    return this.acceptedCount( entry ) > 0 || this.isMarkedDone( entry );
  },

  progress() {
    const shown = this.included();
    const done = shown.filter( ( i ) => this.isComplete( this.images[ i ] ) ).length;
    return { done: done , total: shown.length };
  },

  // Mark (or unmark) the current image done by hand, for images with no AIS
  // worth accepting. Marking moves on to the next incomplete image.
  async toggleDone() {
    const entry = this.images[ this.index ];
    if ( !entry || !this.batch ) return;
    const marking = !this.isMarkedDone( entry );
    this.setDone( entry , marking );
    this.renderPicker();
    if ( marking ) this.nextIncomplete();
  },

  nextIncomplete() {
    const shown = this.included();
    const after = shown.filter( ( i ) => i > this.index ).concat( shown.filter( ( i ) => i < this.index ) );
    const next = after.find( ( i ) => !this.isComplete( this.images[ i ] ) );
    if ( next != null ) this.show( next );
  },

  renderPicker() {
    AisAuto.refresh();
    const select = Dom.get( "ais-image" );
    Dom.clear( select );
    const shown = this.included();
    Dom.text( Dom.get( "ais-images-count" ) , this.images.length ? shown.length + " / " + this.images.length : "" );
    Dom.get( "ais-images-open" ).disabled = !this.images.length;
    Dom.get( "ais-measure" ).disabled = !this.images.length;
    Dom.get( "ais-measure-menu" ).disabled = !this.images.length;
    if ( !shown.length ) {
      select.appendChild( Dom.el( "option" , { text: I18n.get( this.images.length ? "ais.none_included" : "ais.no_images" ) } ) );
      select.disabled = true;
      this.renderCurrent();
      return;
    }
    select.disabled = false;
    shown.forEach( ( i ) => {
      const entry = this.images[ i ];
      const count = this.acceptedCount( entry );
      const mark = this.isComplete( entry ) ? "✓ " : "";
      const single = this.whole( entry ) ? "" : " (" + I18n.get( "ais.single" ) + ")";
      const label = mark + ( i + 1 ) + ". " + entry.key + single + ( count ? "  (" + count + ")" : "" );
      select.appendChild( Dom.el( "option" , { text: label , attrs: { value: String( i ) } } ) );
    } );
    select.value = String( shown.includes( this.index ) ? this.index : shown[ 0 ] );
    this.renderCurrent();
  },

  // Keep showing the current image while it is included; otherwise move to
  // the preferred image, or the nearest included one.
  inclusionChanged( prefer ) {
    this.renderPicker();
    const shown = this.included();
    if ( shown.includes( prefer ) && prefer !== this.index ) {
      this.show( prefer );
      return;
    }
    if ( shown.includes( this.index ) ) return;
    if ( !shown.length ) {
      this.index = -1;
      this.source = null;
      this.bitmap = null;
      this.reject();
      this.status( this.images.length ? I18n.get( "ais.none_included" ) : "" );
      Dom.show( Dom.get( "ais-empty" ) , !this.images.length );
      this.renderCurrent();
      return;
    }
    this.show( shown.find( ( i ) => i > this.index ) ?? shown[ shown.length - 1 ] );
  },

  step( delta ) {
    const shown = this.included();
    if ( !shown.length ) return;
    const at = shown.indexOf( this.index );
    let next;
    if ( at >= 0 ) next = shown[ Math.min( shown.length - 1 , Math.max( 0 , at + delta ) ) ];
    else if ( delta > 0 ) next = shown.find( ( i ) => i > this.index ) ?? shown[ shown.length - 1 ];
    else next = shown.slice().reverse().find( ( i ) => i < this.index ) ?? shown[ 0 ];
    this.direction = delta < 0 ? -1 : 1;
    if ( next !== this.index ) this.show( next , false , true );
  },

  // stepped: by the arrow keys, which may be held down -- an image not in
  // the cache waits a moment, so the ones flown past are not downloaded.
  async show( index , push , stepped ) {
    this.index = index;
    this.result = null;
    this.lastBody = null;
    this.firstClick = null;
    this.editing = null;
    this.hover = null;
    this.preloadToken = null;
    this.views = null;
    this.somata = null;
    const entry = this.images[ index ];
    // The image and its traces together, or neither: the last image's
    // pixels must not be drawn under this one's traces while it loads.
    const slot = entry ? this.cached( entry ) : null;
    if ( slot && slot.img ) this.useImage( slot );
    else {
      this.source = null;
      this.sourceSlot = null;
      this.bitmap = null;
    }
    AisAuto.shown( index );
    AisMeasure.imageShown( index );
    this.renderResult();
    this.renderTable();
    Dom.get( "ais-image" ).value = String( index );
    this.renderCurrent();
    this.setUrl( push );
    this.renderViews();
    if ( this.source ) this.imageReady( entry , index );
    else {
      this.draw();
      this.status( I18n.get( "ais.loading_image" ) );
    }
    try {
      await this.upload( entry );
    } catch ( error ) {
      if ( this.index === index ) {
        this.source = null;
        this.sourceSlot = null;
        this.bitmap = null;
        this.draw();
        this.status( error.message );
      }
      return;
    }
    if ( this.index !== index ) return;   // moved on while uploading
    this.loadViews( entry , index );
    if ( !this.source ) {
      if ( stepped ) {
        await new Promise( ( resolve ) => window.setTimeout( resolve , this.stepDelay ) );
        if ( this.index !== index ) return;
      }
      let loaded;
      try {
        loaded = await this.fetchImage( entry , () => { if ( this.index === index ) this.status( I18n.get( "ais.busy_retrying" ) ); } );
      } catch ( error ) {
        if ( this.index === index ) this.status( error.message );
        return;
      }
      if ( this.index !== index ) return;
      this.useImage( loaded );
      this.imageReady( entry , index );
    }
    this.preload( index );
  },

  // The cached image as the one on screen (its bitmap, at today's brightness).
  useImage( slot ) {
    this.source = slot.img;
    this.sourceSlot = slot;
    this.buildBitmap();
  },

  // The image is in: fit it, its note, drawn with its traces.
  imageReady( entry , index ) {
    if ( !this.locked ) this.fit();
    Dom.show( Dom.get( "ais-empty" ) , false );
    this.status( this.imageNote( entry ) , true );
    this.draw();
    AisMeasure.imageLoaded( index );
  },

  // --- the image previews, decoded and kept ---------------------------------

  // A .czi's view.png used to be its raw AIS channel and is now the processed
  // image: a URL of its own, so a copy cached under the old one is not reused.
  // v=2: before 404s were sent uncached, Cloudflare had browsers keep the
  // 404 of a .czi stained in other than 488 under the old URL for hours.
  viewSrc( entry ) {
    return "/api/ais/files/" + this.sha( entry ) + "/view.png" + ( this.kind( entry ) === "czi" ? "?processed=1&v=2" : "" );
  },

  // The cache's slot for entry's preview (most recently used last), or null.
  cached( entry ) {
    const key = this.viewSrc( entry );
    const slot = this.imageCache.get( key );
    if ( !slot ) return null;
    this.imageCache.delete( key );
    this.imageCache.set( key , slot );
    return slot;
  },

  // Entry's preview, downloaded and decoded once however many ask for it:
  // resolves with its cache slot { img, bitmap, gamma }. onBusy: told when
  // the server refuses (too many requests) and it is asked again.
  fetchImage( entry , onBusy ) {
    const key = this.viewSrc( entry );
    let slot = this.cached( entry );
    if ( !slot ) {
      slot = { img: null , decoded: null , bitmap: null , gamma: null , onBusy: null };
      slot.promise = this.loadImage( key , slot ).then( ( img ) => {
        slot.img = img;
        return slot;
      } , ( error ) => {
        if ( this.imageCache.get( key ) === slot ) this.imageCache.delete( key );   // asked again next time
        throw error;
      } );
      this.imageCache.set( key , slot );
      while ( this.imageCache.size > this.imageCacheSize ) this.imageCache.delete( this.imageCache.keys().next().value );
    }
    if ( onBusy ) slot.onBusy = onBusy;
    return slot.promise;
  },

  // An <img> does not say why it failed: ask again to tell a file that is
  // not there yet from a refusal (too many requests), which is retried.
  async loadImage( src , slot ) {
    for ( let tries = 0; ; tries += 1 ) {
      const img = new Image();
      const loaded = await new Promise( ( resolve ) => {
        img.onload = () => resolve( true );
        img.onerror = () => resolve( false );
        img.src = tries ? src + ( src.includes( "?" ) ? "&" : "?" ) + "retry=" + tries : src;
      } );
      if ( loaded ) {
        // Decoded off the main thread now, not on the first draw. (img.decode()
        // is not used: in some embedded browsers it never settles.)
        try {
          slot.decoded = await createImageBitmap( img );
        } catch ( error ) { /* drawn from the <img> itself */ }
        return img;
      }
      let code = 0;
      let why = "";
      try {
        const response = await fetch( img.src , { credentials: "same-origin" } );
        code = response.status;
        // A file the server has but cannot read says why (a 422).
        if ( code === 422 ) why = ( await response.json() ).error || "";
      } catch ( error ) { /* offline: as before */ }
      if ( code === 429 && tries < 6 ) {
        if ( slot.onBusy ) slot.onBusy();
        await new Promise( ( resolve ) => window.setTimeout( resolve , 5000 * ( tries + 1 ) ) );
        continue;
      }
      if ( code === 404 || code === 0 ) throw new Error( I18n.get( "ais.not_uploaded" ) );
      throw new Error( I18n.get( "ais.view_failed" ) + ( why ? " (" + why + ")" : "" ) );
    }
  },

  // The images either side of the one on screen, the way it is being stepped
  // first, two at a time, only once it is in, so they never hold it up; only ones on the server
  // (uploadAll uploads the rest). Their bitmaps are built when idle.
  preload( index ) {
    const shown = this.included();
    const at = shown.indexOf( index );
    if ( at < 0 ) return;
    const d = this.direction;
    // Nearest first: 4 ahead and 2 behind.
    const near = [ at + d , at + 2 * d , at - d , at + 3 * d , at + 4 * d , at - 2 * d ]
      .filter( ( i ) => i >= 0 && i < shown.length ).map( ( i ) => this.images[ shown[ i ] ] );
    const token = {};
    this.preloadToken = token;
    const idle = () => new Promise( ( resolve ) => {
      if ( window.requestIdleCallback ) window.requestIdleCallback( resolve , { timeout: 500 } );
      else window.setTimeout( resolve , 50 );
    } );
    const worker = async () => {
      while ( near.length ) {
        const entry = near.shift();
        if ( this.preloadToken !== token ) return;
        if ( !this.parts( entry ).every( ( f ) => f.stored ) ) continue;
        let slot;
        try {
          slot = await this.fetchImage( entry );
        } catch ( error ) {
          continue;
        }
        await idle();
        if ( this.preloadToken !== token ) return;
        this.bitmapOf( slot );
      }
    };
    for ( let n = 0; n < this.preloadAtOnce; n += 1 ) worker();
  },

  // Why a lone TIFF is handled the way it is -- until closed for this batch.
  imageNote( entry ) {
    const kind = this.kind( entry );
    if ( this.whole( entry ) ) return "";
    if ( this.noteHidden() ) return "";
    return I18n.get( kind === "raw only" ? "ais.raw_only" : "ais.no_raw" );
  },

  // Make sure the server has the image's files. Files picked in this browser
  // upload (once); Open-path files the server fetches itself; a file only
  // someone else has is "not uploaded yet" until they upload it.
  async upload( entry ) {
    for ( const f of this.parts( entry ) ) {
      if ( f.stored ) continue;
      // Picked on the Batches screen (Add images) rather than here.
      if ( !f.file ) f.file = Batches.fileFor( f.sha );
      if ( !f.file ) throw new Error( I18n.get( "ais.not_uploaded" ) );
      if ( !f.pending ) {
        f.pending = ( async () => {
          await Batches.uploadPatiently( f.file );
          // entry may be the Images dialog's copy, which fileStored can't see.
          f.stored = true;
          this.fileStored( f.sha );
        } )().finally( () => { f.pending = null; } );
      }
      await f.pending;
    }
    if ( entry.files.stack ) entry.files.stack.stored = true;
  },

  // A file is on the server now (uploaded here or by the Batches screen):
  // every copy of the same bytes (duplicates) is.
  fileStored( sha ) {
    this.images.forEach( ( entry ) => {
      this.parts( entry ).forEach( ( f ) => { if ( f.sha === sha ) f.stored = true; } );
      const stack = entry.files.stack;
      if ( stack ) stack.stored = stack.slices.every( ( f ) => f.stored );
    } );
  },

  isStored( sha ) {
    return this.images.some( ( entry ) => this.parts( entry ).some( ( f ) => f.sha === sha && f.stored ) );
  },

  // After an import: upload every included image this browser picked,
  // current first, a few at a time, so the batch is complete for others.
  async uploadAll() {
    const token = {};
    this.uploadToken = token;
    const busy = new Set();
    const waiting = () => this.images.filter( ( entry ) => entry.included && !busy.has( entry ) &&
      this.parts( entry ).some( ( f ) => !f.stored && f.file ) );
    const total = waiting().length;
    let done = 0;
    let failed = false;
    const worker = async () => {
      while ( this.uploadToken === token && !failed ) {
        const left = waiting();
        if ( !left.length ) break;
        const current = this.images[ this.index ];
        const next = left.includes( current ) ? current : left[ 0 ];
        busy.add( next );
        Dom.text( Dom.get( "ais-upload-status" ) , I18n.get( "ais.uploading_n" ).replace( "{done}" , done ).replace( "{total}" , total ) );
        try {
          await this.upload( next );
        } catch ( error ) {
          if ( !failed ) App.showError( error.message );
          failed = true;
          break;
        } finally {
          busy.delete( next );
        }
        done += 1;
      }
    };
    await Promise.all( Array.from( { length: this.concurrency } , worker ) );
    if ( this.uploadToken === token ) Dom.text( Dom.get( "ais-upload-status" ) , "" );
  },

  // Run worker( item ) over items, at most n at a time; resolves when all
  // are done, rejects with the first error (the others still finish).
  async pool( items , n , worker ) {
    let next = 0;
    let failed = null;
    const run = async () => {
      while ( next < items.length && !failed ) {
        const i = next;
        next += 1;
        try {
          await worker( items[ i ] , i );
        } catch ( error ) {
          failed = failed || error;
        }
      }
    };
    await Promise.all( Array.from( { length: Math.min( n , items.length ) } , run ) );
    if ( failed ) throw failed;
  },

  // --- the current image's bar -----------------------------------------------

  // "<stem>" and "<.ext>" of a file name, shown apart.
  splitName( name ) {
    const dot = name.lastIndexOf( "." );
    return dot > 0 ? { stem: name.slice( 0 , dot ) , ext: name.slice( dot ) } : { stem: name , ext: "" };
  },

  renderCurrent() {
    const entry = this.images[ this.index ];
    const bar = Dom.get( "ais-current" );
    Dom.show( bar , Boolean( this.batch && this.images.length ) );
    const { done , total } = this.progress();
    Dom.text( Dom.get( "ais-batch-name" ) , this.batch ? this.batch.name : "" );
    const owner = entry ? this.assigneeOf( entry ) : null;
    Dom.text( Dom.get( "ais-current-assignee" ) , owner == null ? ""
      : owner === ( this.me && this.me.id ) ? I18n.get( "ais.assigned_you" )
      : I18n.get( "ais.assigned_to" ).replace( "{name}" , this.assigneeName( owner ) ) );
    Dom.text( Dom.get( "ais-progress-text" ) , I18n.get( "ais.completed" ).replace( "{done}" , done ).replace( "{total}" , total ) );
    Dom.get( "ais-progress-bar" ).style.width = ( total ? ( 100 * done / total ) : 0 ) + "%";
    Dom.get( "ais-progress-bar-wrap" ).setAttribute( "aria-valuenow" , String( done ) );
    Dom.get( "ais-progress-bar-wrap" ).setAttribute( "aria-valuemax" , String( total ) );
    const buttons = [ "ais-file-open" , "ais-file-reveal" , "ais-file-copy" , "ais-file-link" , "ais-matlab-menu" , "ais-file-done" ];
    // A .czi goes to MATLAB as the TIFF pair it is traced from (Library.matlab_pair).
    Dom.show( Dom.get( "ais-matlab-group" ) , this.canMatlab() );
    if ( !entry ) {
      [ "ais-current-pos" , "ais-current-stem" , "ais-current-ext" , "ais-current-partner" ].forEach( ( id ) => Dom.text( Dom.get( id ) , "" ) );
      buttons.forEach( ( id ) => { Dom.get( id ).disabled = true; } );
      return;
    }
    const shown = this.included();
    const main = entry.files[ this.traced( entry ) ];
    const parts = this.splitName( main.name );
    Dom.text( Dom.get( "ais-current-pos" ) , ( shown.indexOf( this.index ) + 1 ) + " / " + shown.length );
    Dom.text( Dom.get( "ais-current-stem" ) , ( entry.dir ? entry.dir + "/" : "" ) + parts.stem );
    Dom.text( Dom.get( "ais-current-ext" ) , parts.ext );
    const partner = this.kind( entry ) === "pair" ? entry.files.raw.name : "";
    Dom.text( Dom.get( "ais-current-partner" ) , partner ? I18n.get( "ais.profile_from" ).replace( "{name}" , partner ) : "" );
    buttons.forEach( ( id ) => { Dom.get( id ).disabled = false; } );
    Dom.show( Dom.get( "ais-file-reveal" ) , Boolean( main.path && this.local.enabled ) );
    const doneButton = Dom.get( "ais-file-done" );
    const marked = this.isMarkedDone( entry );
    doneButton.setAttribute( "aria-pressed" , String( marked ) );
    doneButton.classList.toggle( "btn-success" , marked );
    doneButton.classList.toggle( "btn-outline-secondary" , !marked );
  },

  currentFile() {
    const entry = this.images[ this.index ];
    return entry ? entry.files[ this.traced( entry ) ] : null;
  },

  // Local files open in their default app (ImageJ, Preview) for whoever runs
  // the server; otherwise the full-resolution preview opens in a new tab.
  async openCurrent() {
    const entry = this.images[ this.index ];
    const f = this.currentFile();
    if ( !f ) return;
    try {
      if ( f.path && this.local.enabled ) {
        await Api.post( "/api/ais/local/open" , { path: f.path } );
      } else {
        await this.upload( entry );
        window.open( "/api/ais/files/" + f.sha + "/view.png" , "_blank" , "noopener" );
      }
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  async revealCurrent() {
    const f = this.currentFile();
    if ( !f || !f.path ) return;
    try {
      await Api.post( "/api/ais/local/reveal" , { path: f.path } );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // The absolute path for an Open-path file; for a picked one the browser
  // only knows the path inside the picked folder.
  copyCurrent() {
    const f = this.currentFile();
    if ( f ) this.copyText( f.path || f.rel || f.name );
  },

  async copyText( text ) {
    try {
      await navigator.clipboard.writeText( text );
    } catch ( error ) {
      const area = Dom.el( "textarea" , { class: "visually-hidden" } );
      area.value = text;
      document.body.appendChild( area );
      area.select();
      document.execCommand( "copy" );
      area.remove();
    }
    Dom.toast( I18n.get( "ui.copied" ) , "ok" );
  },

  // --- MATLAB (app/analysis/matlab.py) ---------------------------------------

  // mode: "open" (the original in the Editor, run it yourself), "run" (the
  // original, run for you) or "replay" (the web click(s) played back).
  matlabBody( entry , mode , clicks , threshold , settings ) {
    return {
      mode: mode || "run",
      processed: this.sha( entry ),
      raw: this.kind( entry ) === "pair" ? this.sha( entry , "raw" ) : null,
      cell: entry.cell,
      threshold: threshold ?? Settings.threshold(),
      settings: Object.assign( {} , settings || Settings.methodSettings() , entry.z_stack ? { pixconv: entry.z_stack.pixel_um } : {} ),
      clicks: clicks || null,
    };
  },

  // mode: "open" or "run", on the settings as they stand.
  verifyInMatlab( entry , mode ) {
    if ( entry ) this.sendToMatlab( entry , this.matlabBody( entry , mode ) );
  },

  async sendToMatlab( entry , body ) {
    if ( !this.canMatlab() ) return;
    try {
      await this.upload( entry );
      // The helper first: it is the computer in front of this person, where
      // the server's own MATLAB may be somewhere else entirely.
      await Api.post( this.local.helper ? "/api/ais/matlab/send" : "/api/ais/local/matlab" , body );
      Dom.toast( I18n.get( "ais.matlab_started" ) , "ok" );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // The shown trace as a replay: its clicks, in the order the original asks
  // for them, and the threshold and settings it was traced with, which the
  // sliders may have moved away from since.
  replayBody() {
    const r = this.result;
    const entry = this.images[ this.index ];
    if ( !r || !this.lastBody || !entry ) return null;
    const clicks = [ this.lastBody.click ];
    if ( r.rethresholded ) clicks.push( this.lastBody.click2 || this.lastBody.click );
    return this.matlabBody( entry , "replay" , clicks , r.threshold_initial , r.settings );
  },

  replayInMatlab() {
    const body = this.replayBody();
    if ( body ) this.sendToMatlab( this.images[ this.index ] , body );
  },

  // The same replay as a zip, for wherever this person's MATLAB is. Needs
  // nothing from the server but the images (app/analysis/matlab_bundle.py).
  async downloadReplay() {
    const body = this.replayBody();
    if ( !body ) return;
    const button = Dom.get( "ais-replay-download" );
    button.disabled = true;
    try {
      await this.upload( this.images[ this.index ] );
      const { blob , name } = await Api.postBlob( "/api/ais/matlab/bundle" , body );
      AisExport.download( blob , name );
    } catch ( error ) {
      App.showError( error.message );
    } finally {
      button.disabled = false;
    }
  },

  // The preview is min..max scaled like imagesc; the brightness slider is a
  // display-only gamma on top, so faint AIS are easier to find.
  buildBitmap() {
    const on = this.views ? this.views.list.filter( ( v ) => this.views.on.has( v.key ) ) : [];
    if ( on.length ) {
      this.buildComposite( on );
      return;
    }
    if ( !this.source ) return;
    this.bitmap = this.sourceSlot && this.sourceSlot.img === this.source
      ? this.bitmapOf( this.sourceSlot ) : this.brightened( this.source );
  },

  // A cached image's bitmap at the brightness set, kept with it: built again
  // only when the brightness has moved since.
  bitmapOf( slot ) {
    const gamma = Number( Dom.get( "ais-gamma" ).value );
    if ( !slot.bitmap || slot.gamma !== gamma ) {
      slot.bitmap = gamma === 1 && slot.decoded ? slot.decoded : this.brightened( slot.img , gamma );
      slot.gamma = gamma;
    }
    return slot.bitmap;
  },

  // The image with the brightness gamma on it; at 1, the image itself.
  brightened( img , gamma ) {
    if ( gamma == null ) gamma = Number( Dom.get( "ais-gamma" ).value );
    if ( gamma === 1 ) return img;
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    const off = document.createElement( "canvas" );
    off.width = w;
    off.height = h;
    const octx = off.getContext( "2d" );
    octx.drawImage( img , 0 , 0 );
    const lut = new Uint8ClampedArray( 256 );
    for ( let v = 0; v < 256; v += 1 ) lut[ v ] = 255 * Math.pow( v / 255 , gamma );
    const data = octx.getImageData( 0 , 0 , w , h );
    const px = data.data;
    for ( let i = 0; i < px.length; i += 4 ) {
      px[ i ] = px[ i + 1 ] = px[ i + 2 ] = lut[ px[ i ] ];
    }
    octx.putImageData( data , 0 , 0 );
    return off;
  },

  // --- channels: the processed image, or channels blended -------------------

  // The image's other views: a .czi's channels in ZEN's colors, a pair's raw
  // file in white. The names switched on for the last image stay on here.
  async loadViews( entry , index ) {
    let list = [];
    if ( this.kind( entry ) === "czi" ) {
      try {
        const out = await Api.request( "/api/ais/files/" + this.sha( entry ) + "/channels" );
        list = out.channels.map( ( c ) => ( { key: "c" + c.index , name: c.name , label: this.channelLabel( c.name ) ,
          color: c.color , src: "/api/ais/files/" + this.sha( entry ) + "/channel/" + c.index + ".png" } ) );
      } catch ( error ) {
        list = [];
      }
    } else if ( this.kind( entry ) === "pair" ) {
      list = [ { key: "raw" , name: "raw" , label: I18n.get( "ais.view_raw" ) , color: "#ffffff" ,
        src: "/api/ais/files/" + this.sha( entry , "raw" ) + "/view.png" } ];
    } else if ( this.kind( entry ) === "stack" ) {
      // The Z slider's, not buttons of their own (renderViews).
      list = entry.files.stack.slices.map( ( f , i ) => ( { key: "z" + i , name: "z" + f.z , label: String( f.z ) , color: "#ffffff" ,
        slice: true , src: "/api/ais/files/" + this.sha( entry ) + "/slice/" + i + ".png" } ) );
    }
    if ( this.index !== index ) return;
    if ( this.showSomata ) this.loadSomata( entry , index );
    this.views = { list: list , on: new Set( list.filter( ( v ) => this.viewWanted.includes( v.name ) ).map( ( v ) => v.key ) ) };
    const slider = Dom.get( "ais-z-slider" );
    slider.max = list.filter( ( v ) => v.slice ).length;
    slider.value = 0;
    this.sliceZ = null;
    this.views.list.filter( ( v ) => this.views.on.has( v.key ) ).forEach( ( v ) => this.loadViewImage( v , index ) );
    this.renderViews();
    if ( this.views.on.size ) {
      this.buildBitmap();
      this.draw();
    }
  },

  // "Alexa Fluor 488" -> "488"; other names as they are.
  channelLabel( name ) {
    const number = /(\d{3})\s*$/.exec( name );
    return number ? number[ 1 ] : name;
  },

  // A Z-stack's slider: 0 is the projection, else that slice, which draw()
  // picks the trace out on where it runs at that depth.
  setSlice( at ) {
    if ( !this.views ) return;
    const view = this.views.list.filter( ( v ) => v.slice )[ at - 1 ];
    this.views.on.clear();
    if ( view ) {
      this.views.on.add( view.key );
      this.loadViewImage( view , this.index );
    }
    this.sliceZ = view ? Number( view.label ) : null;
    this.renderZ();
    this.buildBitmap();
    this.draw();
  },

  renderZ() {
    const list = this.views ? this.views.list.filter( ( v ) => v.slice ) : [];
    Dom.show( Dom.get( "ais-z" ) , list.length > 0 );
    const view = list[ Number( Dom.get( "ais-z-slider" ).value ) - 1 ];
    Dom.text( Dom.get( "ais-z-label" ) , view
      ? I18n.get( "ais.z_slice" ).replace( "{z}" , view.label ).replace( "{n}" , list.length ) : I18n.get( "ais.z_projection" ) );
  },

  // Where a trace runs at the slice shown, within half a slice of it, drawn
  // over everything else on it.
  drawAtSlice( pixels , zPath , width ) {
    if ( this.sliceZ == null || !zPath ) return;
    let run = [];
    const flush = () => {
      this.polyline( run , SLICE_COLOUR , width );
      run = [];
    };
    pixels.forEach( ( p , i ) => {
      if ( zPath[ i ] != null && Math.abs( zPath[ i ] - this.sliceZ ) <= 0.5 ) run.push( p );
      else flush();
    } );
    flush();
  },

  loadViewImage( view , index ) {
    if ( view.img ) return;
    view.img = new Image();
    view.img.onload = () => {
      if ( this.index !== index ) return;
      const wasEmpty = !this.bitmap;
      this.buildBitmap();
      if ( wasEmpty && this.bitmap && !this.locked ) this.fit();
      this.draw();
    };
    view.img.src = view.src;
  },

  // Processed shows it alone; a channel turns on or off, and with none left
  // on, the processed image is back.
  toggleView( key ) {
    if ( !this.views ) return;
    if ( key === "soma" ) {
      this.showSomata = !this.showSomata;
      if ( this.showSomata ) this.loadSomata( this.images[ this.index ] , this.index );
      this.renderViews();
      this.draw();
      return;
    }
    const on = this.views.on;
    if ( key === "processed" ) on.clear();
    else if ( on.has( key ) ) on.delete( key );
    else on.add( key );
    this.viewWanted = this.views.list.filter( ( v ) => on.has( v.key ) ).map( ( v ) => v.name );
    this.views.list.filter( ( v ) => on.has( v.key ) ).forEach( ( v ) => this.loadViewImage( v , this.index ) );
    this.renderViews();
    this.buildBitmap();
    this.draw();
  },

  async loadSomata( entry , index ) {
    if ( this.somata || this.kind( entry ) !== "czi" ) return;
    let found = [];
    try {
      found = ( await Api.request( "/api/ais/files/" + this.sha( entry ) + "/somata" ) ).somata;
    } catch ( error ) {
      this.status( error.message );
    }
    if ( this.index !== index ) return;
    this.somata = found;
    this.draw();
  },

  renderViews() {
    this.renderZ();
    const bar = Dom.get( "ais-channels" );
    const list = this.views ? this.views.list.filter( ( v ) => !v.slice ) : [];
    Dom.show( bar , list.length > 0 );
    if ( !list.length ) {
      Dom.clear( bar );
      return;
    }
    const on = this.views.on;
    const button = ( key , pressed , title , children ) => Dom.el( "button" , {
      class: "btn btn-dark" + ( pressed ? " active" : "" ),
      attrs: { type: "button" , "data-view": key , "aria-pressed": String( pressed ) , title: title },
      children: children,
    } );
    // The dot's color through the DOM: the CSP has no inline style attributes.
    const dot = ( color ) => {
      const node = Dom.el( "span" , { class: "ais-channel-dot me-1" } );
      node.style.backgroundColor = color;
      return node;
    };
    let somaButton = null;
    const buttons = [
      button( "processed" , !on.size , I18n.get( "ais.view_processed_help" ) ,
        [ Dom.el( "i" , { class: "bi bi-image me-1" , attrs: { "aria-hidden": "true" } } ) , Dom.el( "span" , { text: I18n.get( "ais.view_processed" ) } ) ] ),
      ...list.map( ( v ) => button( v.key , on.has( v.key ) , v.name , [ dot( v.color ) , Dom.el( "span" , { text: v.label } ) ] ) ),
    ];
    if ( this.kind( this.images[ this.index ] ) === "czi" ) {
      const soma = button( "soma" , this.showSomata , I18n.get( "ais.view_soma_help" ) ,
        [ dot( SOMA_COLOUR ) , Dom.el( "span" , { text: I18n.get( "ais.view_soma" ) } ) ] );
      soma.classList.add( "ais-view-soma" , "btn-sm" );
      somaButton = soma;
    }
    // Folded, one button names what is shown; open, the rest run along the top.
    const shown = on.size ? list.filter( ( v ) => on.has( v.key ) ).map( ( v ) => v.label ) : [ I18n.get( "ais.view_processed" ) ];
    if ( this.showSomata && somaButton ) shown.push( I18n.get( "ais.view_soma" ) );
    const toggle = Dom.el( "button" , {
      class: "btn btn-dark btn-sm ais-channels-toggle",
      attrs: { id: "ais-channels-toggle" , type: "button" , "aria-expanded": String( this.viewsOpen ) , title: I18n.get( "ais.views" ) },
      children: [
        Dom.el( "i" , { class: "bi bi-layers me-1" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "span" , { text: shown.join( " + " ) } ),
        Dom.el( "i" , { class: "bi ms-1 " + ( this.viewsOpen ? "bi-chevron-left" : "bi-chevron-right" ) , attrs: { "aria-hidden": "true" } } ),
      ],
    } );
    const group = Dom.el( "div" , { class: "btn-group btn-group-sm" , attrs: { role: "group" } , children: buttons } );
    const row = Dom.el( "div" , { class: "ais-channels-list" , children: somaButton ? [ group , somaButton ] : [ group ] } );
    Dom.show( row , this.viewsOpen );
    bar.replaceChildren( toggle , row );
  },

  // The channels switched on, each brightened like the processed image,
  // tinted its color and added together.
  buildComposite( on ) {
    if ( on.some( ( v ) => !v.img || !v.img.complete || !v.img.naturalWidth ) ) return;   // drawn once loaded
    const w = on[ 0 ].img.naturalWidth;
    const h = on[ 0 ].img.naturalHeight;
    const off = document.createElement( "canvas" );
    off.width = w;
    off.height = h;
    const octx = off.getContext( "2d" , { willReadFrequently: true } );
    const gamma = Number( Dom.get( "ais-gamma" ).value );
    const lut = new Float32Array( 256 );
    for ( let v = 0; v < 256; v += 1 ) lut[ v ] = 255 * Math.pow( v / 255 , gamma );
    const sum = new Float32Array( w * h * 3 );
    on.forEach( ( view ) => {
      const hex = view.color.replace( "#" , "" );
      const tint = [ 0 , 2 , 4 ].map( ( i ) => parseInt( hex.slice( i , i + 2 ) , 16 ) / 255 );
      octx.clearRect( 0 , 0 , w , h );
      octx.drawImage( view.img , 0 , 0 , w , h );
      const px = octx.getImageData( 0 , 0 , w , h ).data;
      for ( let i = 0 , j = 0; i < px.length; i += 4 , j += 3 ) {
        const g = lut[ px[ i ] ];
        sum[ j ] += g * tint[ 0 ];
        sum[ j + 1 ] += g * tint[ 1 ];
        sum[ j + 2 ] += g * tint[ 2 ];
      }
    } );
    const data = octx.createImageData( w , h );
    const out = data.data;
    for ( let i = 0 , j = 0; i < out.length; i += 4 , j += 3 ) {
      out[ i ] = sum[ j ];
      out[ i + 1 ] = sum[ j + 1 ];
      out[ i + 2 ] = sum[ j + 2 ];
      out[ i + 3 ] = 255;
    }
    octx.putImageData( data , 0 , 0 );
    this.bitmap = off;
  },

  // --- canvas: zoom, pan, click --------------------------------------------

  resize() {
    const stage = Dom.get( "ais-stage" );
    const dpr = window.devicePixelRatio || 1;
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    this.canvas.width = Math.round( w * dpr );
    this.canvas.height = Math.round( h * dpr );
    this.canvas.style.width = w + "px";
    this.canvas.style.height = h + "px";
    if ( this.bitmap && !this.fitted && !this.locked ) this.fit();
    this.draw();
  },

  fit() {
    if ( !this.bitmap ) return;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    this.fitted = w > 0 && h > 0;
    const scale = Math.min( w / this.bitmap.width , h / this.bitmap.height );
    this.view = { scale: scale , ox: ( w - this.bitmap.width * scale ) / 2 , oy: ( h - this.bitmap.height * scale ) / 2 };
  },

  // Zoom keeping the canvas point (cx, cy) still.
  zoomAt( cx , cy , scale ) {
    if ( !this.bitmap || this.locked ) return;
    scale = Math.min( 40 , Math.max( 0.05 , scale ) );
    this.view.ox = cx - ( cx - this.view.ox ) * scale / this.view.scale;
    this.view.oy = cy - ( cy - this.view.oy ) * scale / this.view.scale;
    this.view.scale = scale;
    this.draw();
  },

  // The toolbar buttons zoom about the middle of the stage.
  zoomBy( factor ) {
    this.zoomAt( this.canvas.clientWidth / 2 , this.canvas.clientHeight / 2 , this.view.scale * factor );
  },

  zoomTo( scale ) {
    this.zoomAt( this.canvas.clientWidth / 2 , this.canvas.clientHeight / 2 , scale );
  },

  // Back to the whole image. Works locked too: then the fitted view becomes
  // the locked one.
  resetView() {
    this.fit();
    if ( this.locked ) this.saveView();
    this.draw();
  },

  setLocked( locked ) {
    this.locked = locked;
    this.saveView();
    this.renderViewTools();
  },

  loadView() {
    try {
      const saved = JSON.parse( window.localStorage.getItem( this.viewKey ) || "null" );
      if ( saved && saved.locked && saved.view && isFinite( saved.view.scale ) ) {
        this.locked = true;
        this.view = { scale: Number( saved.view.scale ) , ox: Number( saved.view.ox ) , oy: Number( saved.view.oy ) };
      }
    } catch ( error ) { /* no saved view */ }
  },

  saveView() {
    try {
      window.localStorage.setItem( this.viewKey , JSON.stringify( { locked: this.locked , view: this.view } ) );
    } catch ( error ) { /* storage blocked: the lock lasts this session */ }
  },

  // Focus mode hides the navbar, sidebar, open buttons and results table, and
  // asks the browser for full screen. The layout survives a reload; full
  // screen itself needs a click, so it does not.
  setFocus( on ) {
    this.focus = on;
    try {
      if ( on ) window.localStorage.setItem( this.focusKey , "1" );
      else window.localStorage.removeItem( this.focusKey );
    } catch ( error ) { /* storage blocked: it just is not remembered */ }
    if ( on && !document.fullscreenElement && document.documentElement.requestFullscreen ) {
      document.documentElement.requestFullscreen().catch( () => {} );
    } else if ( !on && document.fullscreenElement ) {
      document.exitFullscreen().catch( () => {} );
    }
    this.renderFocus();
  },

  loadFocus() {
    try {
      this.focus = window.localStorage.getItem( this.focusKey ) === "1";
    } catch ( error ) {
      this.focus = false;
    }
    this.renderFocus();
  },

  renderFocus() {
    document.documentElement.classList.toggle( "ais-focus" , this.focus );
    this.fitStage();
    const button = Dom.get( "ais-focus" );
    button.setAttribute( "aria-pressed" , String( this.focus ) );
    button.classList.toggle( "active" , this.focus );
    button.querySelector( "i" ).className = "bi " + ( this.focus ? "bi-fullscreen-exit" : "bi-arrows-fullscreen" );
    button.title = I18n.get( this.focus ? "ais.focus_exit" : "ais.focus" );
  },

  // The overlays (Appearance page) are kept per browser: the ones switched off.
  saveLayers() {
    const off = Dom.all( "[data-layer]" ).filter( ( box ) => !box.checked ).map( ( box ) => box.dataset.layer );
    try {
      window.localStorage.setItem( this.layersKey , JSON.stringify( off ) );
    } catch ( error ) { /* storage blocked: it just is not remembered */ }
  },

  loadLayers() {
    let off = [];
    try {
      off = JSON.parse( window.localStorage.getItem( this.layersKey ) || "[]" );
    } catch ( error ) { /* storage blocked or garbled */ }
    if ( !Array.isArray( off ) ) off = [];
    Dom.all( "[data-layer]" ).forEach( ( box ) => { box.checked = !off.includes( box.dataset.layer ); } );
  },

  // Focus mode: the stage takes the window's height below the toolbar and
  // header. Otherwise the stylesheet's height.
  fitStage() {
    const stage = Dom.get( "ais-stage" );
    if ( !this.focus || !stage.offsetParent ) {
      stage.style.height = "";
      return;
    }
    const top = stage.getBoundingClientRect().top + window.scrollY;
    const margin = 8;   // .ais-focus .app-main's bottom padding
    stage.style.height = Math.max( 240 , window.innerHeight - top - margin ) + "px";
  },

  renderViewTools() {
    const lock = Dom.get( "ais-view-lock" );
    lock.setAttribute( "aria-pressed" , String( this.locked ) );
    lock.classList.toggle( "active" , this.locked );
    lock.querySelector( "i" ).className = "bi " + ( this.locked ? "bi-lock-fill" : "bi-unlock" );
    lock.title = I18n.get( this.locked ? "ais.view_unlock" : "ais.view_lock" );
    [ "ais-zoom-in" , "ais-zoom-out" , "ais-zoom-level" ].forEach( ( id ) => { Dom.get( id ).disabled = this.locked; } );
    Dom.text( Dom.get( "ais-zoom-level" ) , Math.round( this.view.scale * 100 ) + "%" );
    this.canvas.classList.toggle( "ais-locked" , this.locked );
  },

  toImage( event ) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: ( event.clientX - rect.left - this.view.ox ) / this.view.scale,
      y: ( event.clientY - rect.top - this.view.oy ) / this.view.scale,
    };
  },

  // Left-drag pans (a press that barely moves is a click, which traces);
  // middle-drag always pans. Both stop while the view is locked. With the
  // Measure tool, a left press on a measure line's end drags that end instead.
  bindCanvas() {
    let down = null;
    this.canvas.addEventListener( "pointerdown" , ( e ) => {
      if ( e.button !== 0 && e.button !== 1 ) return;
      if ( e.button === 1 ) e.preventDefault();
      down = { x: e.clientX , y: e.clientY , ox: this.view.ox , oy: this.view.oy , moved: false , button: e.button };
      if ( e.button === 0 && this.tool === "measure" && AisMeasure.onDown( this.toImage( e ) ) ) down.point = true;
      try { this.canvas.setPointerCapture( e.pointerId ); } catch ( error ) { /* pointer already gone */ }
    } );
    this.canvas.addEventListener( "pointermove" , ( e ) => {
      if ( !down ) {
        this.hoverAt( this.toImage( e ) );
        if ( this.tool === "measure" ) AisMeasure.onMove( this.toImage( e ) );
        return;
      }
      if ( down.point ) {
        AisMeasure.onDrag( this.toImage( e ) );
        return;
      }
      const dx = e.clientX - down.x;
      const dy = e.clientY - down.y;
      if ( Math.abs( dx ) + Math.abs( dy ) > 4 ) down.moved = true;
      if ( down.moved && this.tool === "measure" ) AisMeasure.onMove( null );
      if ( down.moved && !this.locked ) {
        this.view.ox = down.ox + dx;
        this.view.oy = down.oy + dy;
        this.draw();
      }
    } );
    this.canvas.addEventListener( "pointerup" , ( e ) => {
      const wasClick = down && !down.point && !down.moved && down.button === 0;
      if ( down && down.point ) AisMeasure.onUp();
      down = null;
      if ( wasClick && e.button === 0 ) this.onClick( this.toImage( e ) );
    } );
    this.canvas.addEventListener( "pointerleave" , () => {
      this.hoverAt( null );
      AisMeasure.onMove( null );
    } );
    this.canvas.addEventListener( "auxclick" , ( e ) => e.preventDefault() );
    this.canvas.addEventListener( "wheel" , ( e ) => {
      if ( !this.bitmap ) return;
      e.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      this.zoomAt( e.clientX - rect.left , e.clientY - rect.top , this.view.scale * Math.exp( -e.deltaY * 0.0015 ) );
    } , { passive: false } );
    this.canvas.addEventListener( "dblclick" , () => this.resetView() );
  },

  // A click is waiting for Accept / Reject (or for its second click).
  pending() {
    return Boolean( this.lastBody && ( this.result || this.firstClick ) );
  },

  onKey( event ) {
    if ( !Nav || Nav.current() !== "ais" ) return;
    if ( document.body.classList.contains( "modal-open" ) ) return;
    const tag = ( event.target.tagName || "" ).toLowerCase();
    if ( tag === "input" || tag === "select" || tag === "textarea" ) return;
    // Which key does what is shortcuts.js's (the Keyboard shortcuts screen).
    const is = ( action ) => Shortcuts.is( event , "ais." + action );
    if ( is( "undo" ) || is( "redo" ) ) {
      event.preventDefault();
      if ( is( "redo" ) ) this.redo();
      else this.undo();
      return;
    }
    // Measure (ais_measure.js) takes its keys first.
    if ( AisMeasure.onKey( event ) ) return;
    // Cancelling an edit, then (auto) the run's keys. It never changes the
    // tool: only the tool keys (or their buttons) do.
    if ( this.editing && is( "cancel_edit" ) ) {
      event.preventDefault();
      this.reject();
      return;
    }
    if ( AisAuto.onKey( event ) ) return;
    // The nudge keys walk a waiting click, 1 px or 5.
    const nudges = { left: [ -1 , 0 ] , right: [ 1 , 0 ] , up: [ 0 , -1 ] , down: [ 0 , 1 ] };
    const nudge = Object.keys( nudges ).find( ( way ) => is( "nudge_" + way ) || is( "nudge_big_" + way ) );
    if ( nudge ) {
      event.preventDefault();
      if ( !this.pending() ) return;
      const step = is( "nudge_big_" + nudge ) ? 5 : 1;
      this.nudge( nudges[ nudge ][ 0 ] * step , nudges[ nudge ][ 1 ] * step );
      return;
    }
    const actions = {
      accept: () => this.accept(),
      reject: () => this.reject(),
      // Switching images drops a click not yet accepted.
      next_image: () => { if ( this.pending() ) this.reject(); this.step( 1 ); },
      prev_image: () => { if ( this.pending() ) this.reject(); this.step( -1 ); },
      zoom_in: () => this.zoomBy( 1.25 ),
      zoom_out: () => this.zoomBy( 0.8 ),
      reset_view: () => this.resetView(),
      actual_size: () => this.zoomTo( 1 ),
      lock_view: () => this.setLocked( !this.locked ),
      focus: () => this.setFocus( !this.focus ),
      tool_trace: () => this.setTool( "trace" ),
      tool_edit: () => this.setTool( "edit" ),
      tool_delete: () => this.setTool( "delete" ),
      tool_measure: () => this.setTool( "measure" ),
    };
    const action = Object.keys( actions ).find( is );
    if ( !action ) return;
    event.preventDefault();
    actions[ action ]();
  },

  // --- tracing -------------------------------------------------------------

  onClick( point ) {
    const entry = this.images[ this.index ];
    if ( !entry || !this.bitmap ) return;
    if ( point.x < 0 || point.y < 0 || point.x >= this.bitmap.width || point.y >= this.bitmap.height ) return;
    if ( this.tool === "measure" ) {
      AisMeasure.onClick( point );
      return;
    }
    if ( this.tool === "delete" ) {
      const target = this.nearestTrace( point );
      if ( target ) this.deleteTrace( target );
      return;
    }
    if ( this.tool === "edit" ) {
      // A trace (other than the one being edited) is picked; anywhere else,
      // or on the edited trace itself, moves its start there.
      const target = this.nearestTrace( point );
      if ( target && !( this.editing && target.item === this.editing.item ) ) {
        this.startEdit( target );
        return;
      }
      if ( !this.editing ) return;
    } else if ( AisAuto.onClick( point ) ) {
      return;
    }
    // Canvas pixel j spans [j, j+1); in MATLAB axes its centre is j+1.
    const click = [ point.x + 0.5 , point.y + 0.5 ];
    const body = this.firstClick ? { click: this.firstClick , click2: click } : { click: click };
    this.traceBody( body );
  },

  // Walk the pending point: the second click in two-click mode, else the
  // click. Re-traces at once; keys pressed while a trace runs only keep the
  // newest position.
  nudge( dx , dy ) {
    const body = Object.assign( {} , this.lastBody );
    const which = body.click2 ? "click2" : "click";
    body[ which ] = [ body[ which ][ 0 ] + dx , body[ which ][ 1 ] + dy ];
    if ( this.firstClick && !body.click2 ) this.firstClick = body.click;
    this.traceBody( body );
  },

  async traceBody( body ) {
    const entry = this.images[ this.index ];
    if ( !entry ) return;
    if ( this.busy ) {
      this.queuedBody = body;
      this.lastBody = body;
      this.draw();
      return;
    }
    this.busy = true;
    this.lastBody = body;
    this.status( I18n.get( "ais.tracing" ) );
    try {
      const result = await Api.post( "/api/ais/trace" , Object.assign( {
        processed: this.sha( entry ),
        raw: this.kind( entry ) === "pair" ? this.sha( entry , "raw" ) : null,
        threshold: Settings.threshold(),
        settings: Settings.methodSettings(),
      } , Settings.engine() , this.zBody( entry ) , body ) );
      if ( this.images[ this.index ] !== entry ) return;
      const twoClicks = Settings.twoClicks() === "manual";
      if ( twoClicks && !body.click2 && result.rethresholded ) {
        // The original asks for a second click after re-thresholding.
        this.firstClick = body.click;
        this.result = result;
        this.status( I18n.get( "ais.second_click" ).replace( "{threshold}" , this.fmt( result.threshold ) ) );
        this.renderResult( true );
        this.draw();
        return;
      }
      this.firstClick = null;
      this.skipShort( result );
      this.result = Object.assign( result , { image: entry.key , source: this.kind( entry ) } );
      this.status( this.imageNote( entry ) , true );
      this.renderResult();
      this.draw();
    } catch ( error ) {
      this.status( "" );
      App.showError( error.message );
    } finally {
      this.busy = false;
      const queued = this.queuedBody;
      this.queuedBody = null;
      if ( queued ) this.traceBody( queued );
    }
  },

  // Settings > Minimum AIS length: a shorter trace stays on screen but is not
  // ok, so it cannot be accepted.
  skipShort( result ) {
    const min = Settings.minLength();
    const m = result.measures;
    if ( !result.ok || !min || !m || !( m.length_um < min ) ) return;
    result.ok = false;
    result.skipped = true;
    result.error = I18n.get( "ais.too_short" ).replace( "{length}" , m.length_str ).replace( "{min}" , this.fmt( min ) );
  },

  // note: the text is an image note, which gets a close button.
  status( text , note ) {
    const box = Dom.get( "ais-status" );
    Dom.text( Dom.get( "ais-status-text" ) , text );
    Dom.show( Dom.get( "ais-status-close" ) , Boolean( note && text ) );
    Dom.show( box , Boolean( text ) );
  },

  noteHidden() {
    try {
      return Boolean( this.batch ) && window.localStorage.getItem( this.noteKey ) === String( this.batch.id );
    } catch ( error ) {
      return false;
    }
  },

  hideNote() {
    if ( this.batch ) {
      try {
        window.localStorage.setItem( this.noteKey , String( this.batch.id ) );
      } catch ( error ) { /* storage blocked: it comes back on the next image */ }
    }
    this.status( "" );
  },

  // num2str(x, 6) style: six significant digits, no trailing zeros.
  fmt( value ) {
    if ( value == null || !isFinite( value ) ) return "";
    return String( Number( Number( value ).toPrecision( 6 ) ) );
  },

  renderResult( waitingForSecond ) {
    const r = this.result;
    Dom.show( Dom.get( "ais-result-none" ) , !r );
    Dom.show( Dom.get( "ais-result" ) , Boolean( r ) );
    Dom.show( Dom.get( "ais-replay" ) , this.canMatlab() );
    if ( !r ) return;
    const m = r.measures;
    const z = r.z;
    Dom.text( Dom.get( "ais-length" ) , z ? this.fmt( z.length_3d_um ) : m ? m.length_str : I18n.get( "ais.no_length" ) );
    Dom.text( Dom.get( "ais-length-kind" ) , z ? I18n.get( "ais.length_3d" ) : "" );
    const err = Dom.get( "ais-error" );
    Dom.text( err , r.error || "" );
    Dom.show( err , Boolean( r.error ) && !waitingForSecond );

    const dl = Dom.get( "ais-measures" );
    Dom.clear( dl );
    const row = ( key , value ) => {
      if ( value === "" || value == null ) return;
      dl.appendChild( Dom.el( "dt" , { text: I18n.get( "ais." + key ) } ) );
      dl.appendChild( Dom.el( "dd" , { text: value } ) );
    };
    if ( z ) {
      // What to set 3D against; length_um counts rounded pixels, so it isn't.
      row( "m_xy" , this.fmt( z.length_xy_um ) + " µm" );
      row( "m_z_range" , this.fmt( z.z_start ) + " → " + this.fmt( z.z_end ) );
      row( "m_z_span" , this.fmt( z.z_span_um ) + " µm" );
      row( "m_z_step" , this.fmt( z.z_step_um ) + " µm" );
      row( "m_z_clarity" , Math.round( z.z_confidence * 100 ) + "%" );
      row( "m_pixel_length" , m.length_str + " µm" );
    }
    if ( m ) {
      row( "m_start" , this.fmt( m.start_um ) + " µm" );
      row( "m_end" , this.fmt( m.end_um ) + " µm" );
      row( "m_mid" , this.fmt( m.mid_um ) + " µm" );
      row( "m_max" , this.fmt( m.max_um ) + " µm" );
    }
    if ( r.threshold != null ) {
      row( "m_threshold" , r.rethresholded ? this.fmt( r.threshold_initial ) + " → " + this.fmt( r.threshold ) : this.fmt( r.threshold ) );
    }
    if ( r.component ) row( "m_component" , r.component.pixels + " " + I18n.get( "ais.px" ) );
    if ( r.path ) row( "m_trace" , r.path.length + " " + I18n.get( "ais.px" ) + ", " + r.passes + " " + I18n.get( "ais.passes" ) );
    if ( r.clicks ) row( "m_click" , r.clicks.map( ( c ) => "(" + c[ 0 ] + ", " + c[ 1 ] + ")" ).join( " → " ) );
    const changed = Object.entries( r.settings_changed || {} );
    if ( changed.length ) row( "m_settings" , changed.map( ( kv ) => kv[ 0 ] + " = " + kv[ 1 ] ).join( ", " ) );

    const notes = Dom.get( "ais-notes" );
    Dom.clear( notes );
    ( r.notes || [] ).forEach( ( note ) => notes.appendChild( Dom.el( "li" , { text: note } ) ) );
    if ( z && z.z_clipped ) notes.appendChild( Dom.el( "li" , { text: I18n.get( "ais.z_clipped" ) } ) );
    this.renderProfile( r.profile );
    Dom.get( "ais-accept" ).disabled = !( r.ok && !waitingForSecond );
    Dom.text( Dom.get( "ais-accept" ).querySelector( "span" ) , I18n.get( this.editing ? "ais.update" : "ais.accept" ) );
    Dom.get( "ais-replay" ).disabled = !( r.path && !waitingForSecond );
    Dom.get( "ais-replay-download" ).disabled = !( r.path && !waitingForSecond );
  },

  // Normalised, smoothed intensity along the trace with the f line and the
  // start / max / end markers, like the original's figure 3 bottom right.
  renderProfile( profile ) {
    const box = Dom.get( "ais-profile" );
    Dom.clear( box );
    if ( !profile ) return;
    const ns = "http://www.w3.org/2000/svg";
    const W = 320;
    const H = 150;
    const pad = { l: 28 , r: 8 , t: 8 , b: 22 };
    const n = profile.norm_lv.length;
    const xmax = Math.max( n , profile.ais_end ) * profile.pixconv;
    const sx = ( um ) => pad.l + ( um / xmax ) * ( W - pad.l - pad.r );
    const sy = ( v ) => H - pad.b - v * ( H - pad.t - pad.b );
    const svg = document.createElementNS( ns , "svg" );
    svg.setAttribute( "viewBox" , "0 0 " + W + " " + H );
    svg.setAttribute( "role" , "img" );
    const add = ( tag , attrs , text ) => {
      const node = document.createElementNS( ns , tag );
      Object.entries( attrs ).forEach( ( kv ) => node.setAttribute( kv[ 0 ] , kv[ 1 ] ) );
      if ( text != null ) node.textContent = text;
      svg.appendChild( node );
      return node;
    };
    add( "line" , { x1: pad.l , x2: W - pad.r , y1: sy( 0 ) , y2: sy( 0 ) , class: "ais-axis" } );
    add( "line" , { x1: pad.l , x2: pad.l , y1: sy( 0 ) , y2: sy( 1 ) , class: "ais-axis" } );
    add( "text" , { x: pad.l - 4 , y: sy( 1 ) + 4 , class: "ais-tick" , "text-anchor": "end" } , "1" );
    add( "text" , { x: pad.l - 4 , y: sy( 0 ) + 4 , class: "ais-tick" , "text-anchor": "end" } , "0" );
    add( "text" , { x: W - pad.r , y: H - 4 , class: "ais-tick" , "text-anchor": "end" } , this.fmt( xmax ) + " µm" );
    add( "line" , { x1: pad.l , x2: W - pad.r , y1: sy( profile.f ) , y2: sy( profile.f ) , class: "ais-fline" } );
    [ profile.ais_start , profile.max_i , profile.ais_end ].forEach( ( idx ) => {
      add( "line" , { x1: sx( idx * profile.pixconv ) , x2: sx( idx * profile.pixconv ) , y1: sy( 0 ) , y2: sy( 1 ) , class: "ais-marker" } );
    } );
    const points = profile.norm_lv.map( ( v , i ) => sx( ( i + 1 ) * profile.pixconv ).toFixed( 1 ) + "," + sy( v ).toFixed( 1 ) ).join( " " );
    add( "polyline" , { points: points , class: "ais-curve" } );
    box.appendChild( svg );
  },

  // Enter / Accept: a new row, or (Edit tool) the edited trace replaced.
  async accept() {
    const r = this.result;
    const entry = this.images[ this.index ];
    if ( !r || !r.ok || !entry || !this.batch || this.busy ) return;
    try {
      if ( this.editing ) await this.commitEdit( entry , r );
      else await this.saveRow( entry , this.rowFor( entry , r , "" ) );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    this.result = null;
    this.lastBody = null;
    this.editing = null;
    this.status( "" );
    this.renderResult();
    this.renderTable();
    this.renderPicker();
    this.draw();
  },

  // The row the server keeps for an accepted trace r on entry. origin is
  // "auto" for one auto mode found, empty for a click.
  rowFor( entry , r , origin ) {
    const m = r.measures;
    const traced = entry.files[ this.traced( entry ) ];
    const row = {
      // Not the path of a blinded file: it has the original name in it.
      file: ( traced.original ? "" : traced.path ) || traced.rel || traced.name,
      sha: traced.sha,
      length_um: m.length_um,
      length_str: m.length_str,
      start_um: m.start_um,
      end_um: m.end_um,
      mid_um: m.mid_um,
      max_um: m.max_um,
      arc_um: m.arc_um,
      threshold_initial: r.threshold_initial,
      threshold: r.threshold,
      click_x: r.clicks[ 0 ][ 0 ],
      click_y: r.clicks[ 0 ][ 1 ],
      click2_x: r.clicks[ r.clicks.length - 1 ][ 0 ],
      click2_y: r.clicks[ r.clicks.length - 1 ][ 1 ],
      profile_points: r.pixels.length,
      source: r.source,
      smooth: r.settings.smooth,
      notes: ( r.notes || [] ).join( "; " ),
      pixels: r.pixels,
      origin: origin,
      width_um: r.shape ? r.shape.width_um : null,
      brightness: r.shape ? r.shape.brightness : null,
    };
    // The constants it was measured with (app/analysis/ais_auto.py Settings).
    AisExport.settingCols.forEach( ( key ) => { if ( key !== "smooth" ) row[ key ] = r.settings[ key ]; } );
    return Object.assign( row , r.z || {} );
  },

  // Store a row for entry. Shown at once; the outbox (outbox.js) gets it to
  // the server, now or once it can be reached. The caller redraws.
  async saveRow( entry , row ) {
    const saved = await this.postAdd( this.batch.id , entry.key , row );
    this.remember( { kind: "add" , ref: this.refFor( saved ) } );
    return saved;
  },

  async postAdd( batchId , image , row ) {
    const key = Outbox.newId();
    const entry = this.images.find( ( e ) => e.key === image );
    const same = this.batchRows.filter( ( r ) => r.batch_id === batchId && r.image === image ).map( ( r ) => r.n );
    const local = Object.assign( {} , row , {
      id: null , rev: 0 , client_id: key , batch_id: batchId , image: image ,
      batch_name: this.batch && this.batch.id === batchId ? this.batch.name : row.batch_name ,
      cell: entry && entry.cell != null ? entry.cell : row.cell ,
      n: Math.max( 0 , ...same ) + 1 , created_by: this.me ? this.me.id : null , accepted_at: new Date().toISOString() ,
    } );
    // As the server keeps an add: no edit, and no soma (measured again).
    [ "edited_at" , "edited_by" , "soma_um" , "soma_px" , "soma_ais_x" , "soma_ais_y" , "soma_x" , "soma_y" , "soma_at" , "soma_by" ]
      .forEach( ( k ) => delete local[ k ] );
    this.batchRows.push( local );
    if ( this.allRows ) this.allRows.push( local );
    Outbox.add( { kind: "create" , bucket: "results" , key: key , path: "/api/ais/results" , label: this.rowLabel( local ) ,
      body: { batch_id: batchId , image: image , row: row , client_id: key } } );
    return local;
  },

  // Mark entry done (shared progress), unless it is already.
  async markDone( entry ) {
    if ( this.isMarkedDone( entry ) ) return;
    this.setDone( entry , true );
  },

  // Done or not, here at once and on the server when it can be reached.
  setDone( entry , done ) {
    const skipped = this.batch.skipped.filter( ( key ) => key !== entry.key );
    if ( done ) skipped.push( entry.key );
    this.batch.skipped = skipped;
    Outbox.add( { kind: "done" , bucket: "done" , key: this.batch.id + ":" + entry.key , batchId: this.batch.id ,
      path: "/api/ais/batches/" + this.batch.id + "/done" , body: { image: entry.key , done: done } ,
      label: ( I18n.get( "outbox.done" ) || "done mark on {image}" ).replace( "{image}" , entry.key ) } );
  },

  // A row's own name in the outbox: the client_id it was accepted with, or
  // its server id for one from before rows had one.
  rowKey( row ) {
    return row.client_id || "r" + row.id;
  },

  rowLabel( row ) {
    return ( I18n.get( "outbox.row" ) || "AIS {n} on {image}" ).replace( "{n}" , row.n ).replace( "{image}" , row.image );
  },

  // What the outbox says back about rows and done marks (outbox.js).
  outboxHandlers() {
    const owned = [ "id" , "n" , "rev" , "created_by" , "accepted_at" , "edited_at" , "edited_by" , "soma_at" , "soma_by" ,
      "batch_name" , "cell" ];
    const redraw = () => { this.renderTable(); this.renderPicker(); this.draw(); };
    return {
      results: {
        reply: ( item , out ) => {
          if ( !out ) return;
          if ( item.kind === "delete" ) {
            const n = new Map( ( out.renumbered || [] ).map( ( r ) => [ r.id , r.n ] ) );
            [ this.batchRows , this.allRows ].forEach( ( list ) => list && list.forEach( ( r ) => { if ( n.has( r.id ) ) r.n = n.get( r.id ); } ) );
          } else {
            [ this.batchRows , this.allRows ].forEach( ( list ) => list && list.forEach( ( r ) => {
              if ( this.rowKey( r ) === item.key || ( r.client_id && r.client_id === item.key ) ) {
                owned.forEach( ( k ) => { if ( k in out ) r[ k ] = out[ k ]; } );
              }
            } ) );
          }
          redraw();
        },
        resync: async () => {
          if ( !this.batch ) return;
          await this.loadBatchRows();
          if ( this.allRows ) { this.allRows = null; this.loadTable(); }
          redraw();
        },
      },
      done: {
        reply: ( item , out ) => {
          if ( !out || !this.batch || this.batch.id !== item.batchId ) return;
          // A later mark still to go would be undone by this answer's list.
          if ( Outbox.items.some( ( other ) => other !== item && other.kind === "done" && other.batchId === item.batchId ) ) return;
          this.batch.skipped = out.skipped;
          this.renderPicker();
        },
        resync: () => {},
      },
    };
  },

  reject() {
    this.result = null;
    this.lastBody = null;
    this.queuedBody = null;
    this.firstClick = null;
    this.editing = null;
    this.status( "" );
    this.renderResult();
    this.draw();
  },

  // --- the Trace / Edit / Delete / Measure tools --------------------------------------

  // A tool stays on until another is picked: picking it again keeps it.
  setTool( tool ) {
    const next = tool;
    if ( this.editing && next !== "edit" ) this.reject();
    const was = this.tool;
    this.tool = next;
    this.hover = null;
    this.renderTools();
    if ( was === "measure" && next !== "measure" ) AisMeasure.reset();
    if ( next === "measure" && was !== "measure" ) AisMeasure.start();
    this.draw();
  },

  renderTools() {
    Dom.all( "[data-tool]" ).forEach( ( button ) => {
      const on = button.dataset.tool === this.tool;
      button.classList.toggle( "active" , on );
      button.setAttribute( "aria-pressed" , String( on ) );
    } );
    this.canvas.classList.toggle( "ais-tool-delete" , this.tool === "delete" );
    this.canvas.classList.toggle( "ais-tool-measure" , this.tool === "measure" );
    this.canvas.classList.toggle( "ais-hit" , Boolean( this.hover ) );
  },

  // Every trace on the image a tool can act on: auto's candidates, then the
  // saved rows. Each { kind, item, pixels }.
  traces() {
    const entry = this.images[ this.index ];
    if ( !entry ) return [];
    return AisAuto.shownCandidates().map( ( c ) => ( { kind: "candidate" , item: c , pixels: c.result.pixels } ) )
      .concat( this.savedRows( entry ).map( ( row ) => ( { kind: "row" , item: row , pixels: row.pixels } ) ) );
  },

  // The trace within a few screen pixels of point (image units), or null.
  nearestTrace( point ) {
    const reach = Math.max( 2 , 8 / this.view.scale );
    let best = null;
    let bestD = reach * reach;
    this.traces().forEach( ( target ) => {
      ( target.pixels || [] ).forEach( ( p ) => {
        const dx = p[ 0 ] - 0.5 - point.x;
        const dy = p[ 1 ] - 0.5 - point.y;
        const d = dx * dx + dy * dy;
        if ( d <= bestD ) {
          bestD = d;
          best = target;
        }
      } );
    } );
    return best;
  },

  // Edit and Delete lock on to the trace under the pointer.
  hoverAt( point ) {
    const target = point && ( this.tool === "edit" || this.tool === "delete" ) ? this.nearestTrace( point ) : null;
    if ( ( target && target.item ) === ( this.hover && this.hover.item ) ) return;
    this.hover = target;
    this.renderTools();
    this.draw();
  },

  // Edit: trace the target again from its start, which Alt+arrow keys then
  // walk and a click moves; Enter keeps the new trace (commitEdit).
  startEdit( target ) {
    const item = target.item;
    let body;
    if ( target.kind === "candidate" ) {
      body = { click: ( item.result.seed || item.result.clicks[ 0 ] ).slice() };
    } else {
      body = { click: [ item.click_x , item.click_y ] };
      if ( item.click2_x != null && ( item.click2_x !== item.click_x || item.click2_y !== item.click_y ) ) {
        body.click2 = [ item.click2_x , item.click2_y ];
      }
    }
    this.editing = target;
    this.firstClick = null;
    this.traceBody( body );
  },

  async commitEdit( entry , r ) {
    const target = this.editing;
    if ( target.kind === "candidate" ) {
      AisAuto.replaceCandidate( target.item , Object.assign( r , { seed: r.clicks[ 0 ] } ) );
      return;
    }
    const old = target.item;
    const ref = this.refFor( old );
    const saved = await this.postUpdate( old , this.rowFor( entry , r , old.origin || "" ) );
    this.remember( { kind: "edit" , ref: ref , before: old , after: saved } );
  },

  // The row as this page has it now, by its key (an older copy may be held).
  currentRow( row ) {
    const key = this.rowKey( row );
    return this.batchRows.find( ( r ) => this.rowKey( r ) === key ) ||
      ( this.allRows && this.allRows.find( ( r ) => this.rowKey( r ) === key ) ) || row;
  },

  // old's place in the lists (and its ref) taken by local.
  swapRow( old , local ) {
    const key = this.rowKey( old );
    const swap = ( list ) => list && list.forEach( ( r , i ) => { if ( this.rowKey( r ) === key ) list[ i ] = local; } );
    swap( this.batchRows );
    swap( this.allRows );
    const ref = this.refs.get( key );
    if ( ref ) ref.row = local;
  },

  // An edit (or an undo of one): the trace replaced, keeping the row's
  // number, origin and who accepted it, as the server does.
  async postUpdate( old , row ) {
    const current = this.currentRow( old );
    const local = Object.assign( {} , row );
    [ "id" , "client_id" , "rev" , "batch_id" , "batch_name" , "image" , "cell" , "n" , "created_by" , "accepted_at" ]
      .forEach( ( k ) => { if ( k in current ) local[ k ] = current[ k ]; } );
    // An edit drops the soma distance on the server (the start may move).
    [ "soma_um" , "soma_px" , "soma_ais_x" , "soma_ais_y" , "soma_x" , "soma_y" , "soma_at" , "soma_by" ].forEach( ( k ) => delete local[ k ] );
    // How auto mode found it stays too (app/models/ais.py update_result).
    Object.keys( local ).forEach( ( k ) => { if ( k.startsWith( "auto_" ) ) delete local[ k ]; } );
    AisExport.autoCols.forEach( ( k ) => { if ( k in current ) local[ k ] = current[ k ]; } );
    Object.assign( local , { origin: current.origin || "" , edited_at: new Date().toISOString() , edited_by: this.me ? this.me.id : null } );
    this.swapRow( current , local );
    Outbox.add( { kind: "update" , bucket: "results" , key: this.rowKey( current ) , path: "/api/ais/results/{id}/update" ,
      label: this.rowLabel( current ) , body: { row: row } } , { id: current.id , rev: current.rev } );
    return local;
  },

  // The Measure tool's AIS -> soma distance (null clears it): the row with
  // it, in place of the old one.
  async postSoma( row , soma ) {
    const current = this.currentRow( row );
    const local = Object.assign( {} , current );
    [ "soma_um" , "soma_px" , "soma_ais_x" , "soma_ais_y" , "soma_x" , "soma_y" ].forEach( ( k ) => { local[ k ] = soma ? soma[ k ] : null; } );
    local.soma_at = soma ? new Date().toISOString() : null;
    local.soma_by = soma && this.me ? this.me.id : null;
    this.swapRow( current , local );
    Outbox.add( { kind: "update" , bucket: "results" , key: this.rowKey( current ) , path: "/api/ais/results/{id}/soma" ,
      label: this.rowLabel( current ) , body: { soma: soma } } , { id: current.id , rev: current.rev } );
    return local;
  },

  deleteTrace( target ) {
    this.hover = null;
    if ( this.editing && this.editing.item === target.item ) this.reject();
    if ( target.kind === "candidate" ) AisAuto.removeCandidate( target.item );
    else this.deleteRow( target.item );
    this.renderTools();
  },

  // --- results (on the server) -------------------------------------------------

  async loadBatchRows() {
    const batchId = this.batch ? this.batch.id : null;
    if ( this.historyBatch !== batchId ) this.clearHistory( batchId );
    if ( !this.batch ) {
      this.batchRows = [];
      this.measurements = [];
      return;
    }
    // Edits still queued from before (a reload, a sign-in) go first, so what
    // comes back has them in it; still queued after a few seconds (the
    // server is away), its new rows are laid over what does come back.
    await Outbox.settled( 3000 );
    try {
      this.batchRows = this.withQueued( ( await Api.request( "/api/ais/results?batch=" + this.batch.id ) ).results );
    } catch ( error ) {
      this.batchRows = [];
      App.showError( error.message );
    }
    await this.loadMeasurements();
    this.renderTable();
  },

  // Rows the outbox has yet to deliver for the open batch: added ones shown,
  // deleted ones not.
  withQueued( rows ) {
    const queued = Outbox.items.filter( ( item ) => item.bucket === "results" );
    if ( !queued.length ) return rows;
    const gone = new Set( queued.filter( ( item ) => item.kind === "delete" ).map( ( item ) => item.key ) );
    const out = rows.filter( ( r ) => !gone.has( this.rowKey( r ) ) );
    queued.filter( ( item ) => item.kind === "create" && item.body.batch_id === this.batch.id && !gone.has( item.key ) &&
      !out.some( ( r ) => r.client_id === item.key ) ).forEach( ( item ) => {
      const same = out.filter( ( r ) => r.image === item.body.image ).map( ( r ) => r.n );
      out.push( Object.assign( {} , item.body.row , { id: null , rev: 0 , client_id: item.key , batch_id: item.body.batch_id ,
        image: item.body.image , n: Math.max( 0 , ...same ) + 1 } ) );
    } );
    return out;
  },

  // The batch's recorded lines (the Measure tool's Record switch), each with
  // its ends as a and b, the way the tool works on them.
  async loadMeasurements() {
    try {
      const found = await Api.request( "/api/ais/measurements?batch=" + this.batch.id );
      const queued = Outbox.items.filter( ( item ) => item.bucket === "measurements" );
      const gone = new Set( queued.filter( ( item ) => item.kind === "delete" ).map( ( item ) => item.key ) );
      const lines = found.measurements.filter( ( line ) => !gone.has( AisMeasure.lineKey( line ) ) );
      // Lines the outbox has yet to deliver (the server is away), shown too.
      queued.filter( ( item ) => item.kind === "create" && item.body.batch_id === this.batch.id && !gone.has( item.key ) &&
        !lines.some( ( line ) => line.client_id === item.key ) ).forEach( ( item ) => {
        const same = lines.filter( ( line ) => line.image === item.body.image ).map( ( line ) => line.n );
        lines.push( Object.assign( {} , item.body.measurement , { id: null , rev: 0 , client_id: item.key ,
          batch_id: item.body.batch_id , image: item.body.image , n: Math.max( 0 , ...same ) + 1 } ) );
      } );
      this.measurements = lines.map( ( line ) => this.lineEnds( line ) );
    } catch ( error ) {
      this.measurements = [];
      App.showError( error.message );
    }
  },

  lineEnds( line ) {
    return Object.assign( line , { a: [ line.a_x , line.a_y ] , b: [ line.b_x , line.b_y ] } );
  },

  // An image's recorded lines, by number.
  measurementsOn( entry ) {
    return this.measurements.filter( ( line ) => line.image === entry.key ).sort( ( p , q ) => p.n - q.n );
  },

  async loadTable() {
    if ( Dom.get( "ais-table-scope" ).value === "all" ) {
      try {
        this.allRows = ( await Api.request( "/api/ais/results?batch=all" ) ).results;
        this.allMeasurements = ( await Api.request( "/api/ais/measurements?batch=all" ) ).measurements;
      } catch ( error ) {
        App.showError( error.message );
      }
    }
    this.renderTable();
  },

  // The rows the table shows and the exports write: the image on screen's,
  // this batch's, or all.
  shownRows() {
    const scope = Dom.get( "ais-table-scope" ).value;
    if ( scope === "all" || !this.batch ) return this.allRows || [];
    if ( scope === "image" ) {
      const entry = this.images[ this.index ];
      return entry ? this.savedRows( entry ) : [];
    }
    return this.batchRows;
  },

  // The recorded lines the exports write, by the same scope.
  shownMeasurements() {
    const scope = Dom.get( "ais-table-scope" ).value;
    if ( scope === "all" || !this.batch ) {
      // The open batch's as they are now: they change without a fetch.
      const others = ( this.allMeasurements || [] ).filter( ( line ) => !this.batch || line.batch_id !== this.batch.id );
      return others.concat( this.batch ? this.measurements : [] );
    }
    if ( scope === "image" ) {
      const entry = this.images[ this.index ];
      return entry ? this.measurementsOn( entry ) : [];
    }
    return this.measurements;
  },

  // Newest first.
  renderTable() {
    const body = Dom.get( "ais-table" ).querySelector( "tbody" );
    Dom.clear( body );
    this.shownRows().slice().reverse().forEach( ( row ) => {
      const del = Dom.el( "button" , {
        class: "btn btn-sm btn-link text-danger p-0",
        attrs: { title: I18n.get( "ais.reject" ) },
        children: [ Dom.el( "i" , { class: "bi bi-trash" } ) ],
        on: { click: () => this.deleteRow( row ) },
      } );
      const name = Dom.el( "a" , {
        text: row.image,
        attrs: { href: this.urlFor( { id: row.batch_id , name: row.batch_name || "" } , { key: row.image } ) , title: row.file || row.image },
      } );
      body.appendChild( Dom.el( "tr" , { children: [
        Dom.el( "td" , { class: "text-truncate ais-cell-name" , children: [ name ] } ),
        Dom.el( "td" , { text: row.n } ),
        Dom.el( "td" , { text: row.length_3d_um != null ? this.fmt( row.length_3d_um ) + " " + I18n.get( "ais.length_3d" ) : row.length_str ,
          class: "fw-semibold" } ),
        Dom.el( "td" , { text: this.fmt( row.start_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.end_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.max_um ) } ),
        Dom.el( "td" , { children: [ this.somaCell( row ) ] } ),
        Dom.el( "td" , { text: this.fmt( row.threshold ) } ),
        Dom.el( "td" , { text: "(" + row.click_x + ", " + row.click_y + ")" } ),
        Dom.el( "td" , { text: ( row.source || "pair" ) + ( row.origin === "auto" ? " · " + I18n.get( "ais.auto_origin" ) : "" ) } ),
        Dom.el( "td" , { text: row.batch_name || "" , class: "text-truncate ais-batch-name" } ),
        Dom.el( "td" , { children: [ del ] } ),
      ] } ) );
    } );
    const rows = this.shownRows().length;
    const lines = this.shownMeasurements().length;
    Dom.get( "ais-export" ).disabled = !rows && !lines;
    Dom.get( "ais-export-csv" ).disabled = !rows;
    Dom.show( Dom.get( "ais-export-measurements-item" ) , Boolean( lines ) );
    AisMeasure.render();
  },

  // The AIS -> soma distance (Measure tool); on this batch's rows, a link
  // that measures it.
  somaCell( row ) {
    const text = row.soma_um != null ? row.soma_um.toFixed( 2 ) : "—";
    if ( !this.batch || row.batch_id !== this.batch.id ) return Dom.el( "span" , { text: text } );
    return Dom.el( "button" , {
      class: "btn btn-link btn-sm p-0 align-baseline" + ( row.soma_um == null ? " text-body-secondary" : "" ),
      text: text,
      attrs: { type: "button" , title: I18n.get( "ais.measure_row" ) },
      on: { click: () => AisMeasure.measureRow( row ) },
    } );
  },

  // Delete a saved row; the server renumbers the rest of its image 1..k.
  async deleteRow( row ) {
    const ref = this.refFor( row );
    await this.postDelete( row );
    this.remember( { kind: "delete" , ref: ref } );
  },

  // Gone here at once, the rest of its image renumbered 1..k as the server
  // will; the outbox deletes it there.
  async postDelete( row ) {
    const current = this.currentRow( row );
    const key = this.rowKey( current );
    if ( this.editing && this.editing.item && this.rowKey( this.editing.item ) === key ) this.reject();
    const keep = ( list ) => {
      const rest = list.filter( ( r ) => this.rowKey( r ) !== key );
      rest.filter( ( r ) => r.batch_id === current.batch_id && r.image === current.image )
        .sort( ( p , q ) => p.n - q.n ).forEach( ( r , i ) => { r.n = i + 1; } );
      return rest;
    };
    this.batchRows = keep( this.batchRows );
    if ( this.allRows ) this.allRows = keep( this.allRows );
    Outbox.add( { kind: "delete" , bucket: "results" , key: key , path: "/api/ais/results/{id}/delete" ,
      label: this.rowLabel( current ) , body: {} } , { id: current.id , rev: current.rev } );
    AisAuto.rowDeleted();
    this.renderTable();
    this.renderPicker();
    this.draw();
  },

  // --- undo / redo (of the saved rows) ------------------------------------------

  refFor( row ) {
    const key = this.rowKey( row );
    let ref = this.refs.get( key );
    if ( !ref ) {
      ref = { row: row };
      this.refs.set( key , ref );
    }
    return ref;
  },

  remember( step ) {
    this.undoStack.push( step );
    this.redoStack = [];
    this.renderHistory();
  },

  clearHistory( batchId ) {
    this.undoStack = [];
    this.redoStack = [];
    this.refs = new Map();
    this.historyBatch = batchId;
    this.renderHistory();
  },

  renderHistory() {
    Dom.get( "ais-undo" ).disabled = !this.undoStack.length || this.historyBusy;
    Dom.get( "ais-redo" ).disabled = !this.redoStack.length || this.historyBusy;
  },

  undo() { return this.replay( this.undoStack , this.redoStack , true ); },
  redo() { return this.replay( this.redoStack , this.undoStack , false ); },

  // Take the last step off from and do it backwards (undo) or again (redo);
  // it then goes on to. A step that fails (someone else changed the row)
  // is dropped.
  async replay( from , to , backwards ) {
    if ( this.historyBusy || this.busy || !from.length ) return;
    const step = from.pop();
    const ref = step.ref;
    const remove = ( step.kind === "add" ) === backwards;
    this.historyBusy = true;
    this.renderHistory();
    try {
      if ( step.kind === "edit" ) {
        await this.postUpdate( ref.row , backwards ? step.before : step.after );
      } else if ( remove ) {
        await this.postDelete( ref.row );
      } else {
        const saved = await this.postAdd( ref.row.batch_id , ref.row.image , ref.row );
        this.refs.delete( this.rowKey( ref.row ) );
        ref.row = saved;
        this.refs.set( this.rowKey( saved ) , ref );
      }
      to.push( step );
    } catch ( error ) {
      App.showError( error.message );
    } finally {
      this.historyBusy = false;
      this.renderHistory();
    }
    if ( this.editing ) this.reject();
    this.renderTable();
    this.renderPicker();
    this.draw();
  },

  // --- drawing -------------------------------------------------------------

  layer( name ) {
    const box = document.querySelector( '[data-layer="' + name + '"]' );
    return !box || box.checked;
  },

  // Accepted rows for the image on screen.
  savedRows( entry ) {
    return this.batchRows.filter( ( row ) => row.image === entry.key );
  },

  draw() {
    const ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform( 1 , 0 , 0 , 1 , 0 , 0 );
    ctx.clearRect( 0 , 0 , this.canvas.width , this.canvas.height );
    Dom.text( Dom.get( "ais-zoom-level" ) , Math.round( this.view.scale * 100 ) + "%" );
    if ( !this.bitmap ) return;
    const s = this.view.scale;
    ctx.setTransform( dpr * s , 0 , 0 , dpr * s , dpr * this.view.ox , dpr * this.view.oy );
    ctx.imageSmoothingEnabled = s < 1;
    ctx.drawImage( this.bitmap , 0 , 0 );
    const lw = Settings.lineWidth() / s;

    const entry = this.images[ this.index ];
    if ( entry && this.layer( "saved" ) ) {
      this.savedRows( entry ).forEach( ( row ) => {
        this.polyline( row.pixels , "rgba(60, 220, 120, 0.9)" , lw );
        this.drawAtSlice( row.pixels , row.z_path , lw * 2.5 );
        const p = row.pixels[ 0 ];
        if ( p ) {
          ctx.fillStyle = "rgba(60, 220, 120, 1)";
          ctx.font = ( 12 / s ) + "px sans-serif";
          ctx.fillText( String( row.n ) , p[ 0 ] + 3 / s , p[ 1 ] - 3 / s );
        }
      } );
    }

    if ( this.showSomata && this.somata ) this.somata.forEach( ( outline ) => this.dots( outline , SOMA_COLOUR ) );

    AisAuto.draw( ctx , s , lw );
    AisMeasure.draw( ctx , s , lw );

    // Edit / Delete: the trace under the pointer, thick; the one being edited,
    // dashed white under its new trace.
    if ( this.hover ) {
      this.polyline( this.hover.pixels , this.tool === "delete" ? "rgba(255, 50, 50, 1)" : "rgba(255, 190, 0, 1)" , lw * 3 );
    }
    if ( this.editing ) {
      ctx.setLineDash( [ 4 / s , 3 / s ] );
      this.polyline( this.editing.pixels , "rgba(255, 255, 255, 0.9)" , lw * 1.5 );
      ctx.setLineDash( [] );
    }

    const r = this.result;
    if ( r ) {
      if ( r.component && this.layer( "component" ) ) this.dots( r.component.edge , "rgba(0, 200, 255, 0.55)" );
      if ( r.skeleton && this.layer( "skeleton" ) ) this.dots( r.skeleton , "rgba(255, 40, 40, 0.95)" );
      if ( r.pixels && this.layer( "trace" ) ) this.polyline( r.pixels , "rgba(40, 110, 255, 1)" , lw );
      if ( r.spline && this.layer( "spline" ) ) this.polyline( r.spline , "rgba(255, 225, 0, 1)" , lw );
      if ( r.pixels && r.z ) this.drawAtSlice( r.pixels , r.z.z_path , lw * 2.5 );
      if ( r.start ) this.cross( r.start , "rgba(255, 255, 255, 1)" , ( 4 + Settings.lineWidth() ) / s , lw );
    }
    // The click(s) where they are now: a nudge shows before its trace returns.
    if ( this.lastBody ) {
      [ this.lastBody.click , this.lastBody.click2 ].filter( Boolean )
        .forEach( ( c ) => this.cross( c , "rgba(255, 150, 0, 1)" , ( 6 + Settings.lineWidth() ) / s , lw ) );
    }
  },

  // Pixels (x, y), 1-based: each fills its own square.
  dots( points , colour ) {
    const ctx = this.ctx;
    ctx.fillStyle = colour;
    points.forEach( ( p ) => ctx.fillRect( p[ 0 ] - 1 , p[ 1 ] - 1 , 1 , 1 ) );
  },

  // Points in MATLAB axes coordinates: centre of pixel x is x - 0.5 here.
  polyline( points , colour , width , ctx ) {
    if ( !points || points.length < 2 ) return;
    ctx = ctx || this.ctx;
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.lineJoin = "round";
    ctx.beginPath();
    points.forEach( ( p , i ) => {
      if ( i === 0 ) ctx.moveTo( p[ 0 ] - 0.5 , p[ 1 ] - 0.5 );
      else ctx.lineTo( p[ 0 ] - 0.5 , p[ 1 ] - 0.5 );
    } );
    ctx.stroke();
  },

  cross( p , colour , size , width ) {
    const ctx = this.ctx;
    const x = p[ 0 ] - 0.5;
    const y = p[ 1 ] - 0.5;
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo( x - size , y ); ctx.lineTo( x + size , y );
    ctx.moveTo( x , y - size ); ctx.lineTo( x , y + size );
    ctx.stroke();
  },
};
