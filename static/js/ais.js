// The Process screen: open a folder of TIFF pairs (or lone TIFFs), click near
// an AIS, see the original ais_auto.m's trace and length, accept or reject it.
//
// The analysis is all server-side (app/analysis/). Each opened folder becomes
// a batch on the server (app/models/ais.py), shared with every signed-in
// user: its images, which are done, and the accepted AIS. The URL names the
// batch and image (#ais/<id>-<folder>/<image>), so a link opens the same
// image for anyone. ais_images.js holds the Images, Open path and Batches
// dialogs, ais_export.js the CSV and ZIP exports.
//
// A folder picked in the browser is hashed here first (sha-256, the id the
// server stores files under), so the batch, its duplicates and its link exist
// at once; the files then upload in the background. An Open-path folder is
// read by the server itself.
//
// Coordinates sent to and received from the server are MATLAB axes
// coordinates: x = column, y = row, pixel centres at 1..n. On the canvas a
// pixel (x, y) covers [x-1, x) x [y-1, y) in image units.
const Ais = {
  processedSuffix: ".tif - Processed method 2.5.tif",
  legacyResultsKey: "ais-results",
  includeKey: "ais-include-",
  viewKey: "ais-view",
  lastKey: "ais-last",   // the last batch and image, for a bare #ais or /
  focusKey: "ais-focus",
  hintKey: "ais-hint-hidden",
  noteKey: "ais-note-hidden",   // the batch whose single-image note was closed
  // An image: { key, cell, dir, dup_of?, included, files: { processed?, raw? } }
  // with a file { name, rel, sha, size, stored, path?, file? } -- `file` only
  // in the browser that picked it, `path` only for Open path.
  images: [],
  batch: null,           // the server's batch record
  me: null,
  local: { enabled: false , platform: "" , matlab: false },
  index: -1,
  bitmap: null,          // the current image, brightness applied, as a canvas
  source: null,          // its decoded <img>
  view: { scale: 1 , ox: 0 , oy: 0 },
  locked: false,         // pan and zoom frozen, the same view on every image
  focus: false,          // focus mode: only the image, navigation and result
  result: null,          // the last trace answer from the server
  lastBody: null,        // the clicks that produced it, for nudging
  queuedBody: null,      // a nudge that arrived while a trace was running
  firstClick: null,      // two-click mode: waiting for the second click
  batchRows: [],         // accepted AIS of the open batch
  allRows: null,         // every batch's, loaded when the table shows all
  busy: false,

  init( me ) {
    this.me = me || null;
    this.canvas = Dom.get( "ais-canvas" );
    this.ctx = this.canvas.getContext( "2d" );
    this.loadView();

    Dom.get( "ais-folder" ).addEventListener( "change" , ( e ) => { this.openFiles( e.target.files ); e.target.value = ""; } );
    Dom.get( "ais-files" ).addEventListener( "change" , ( e ) => { this.openFiles( e.target.files ); e.target.value = ""; } );
    Dom.get( "ais-image" ).addEventListener( "change" , ( e ) => this.show( Number( e.target.value ) ) );
    Dom.get( "ais-prev" ).addEventListener( "click" , () => this.step( -1 ) );
    Dom.get( "ais-next" ).addEventListener( "click" , () => this.step( 1 ) );
    Dom.get( "ais-gamma" ).addEventListener( "input" , () => { this.buildBitmap(); this.draw(); } );
    Dom.all( "[data-layer]" ).forEach( ( box ) => box.addEventListener( "change" , () => this.draw() ) );
    Dom.get( "ais-accept" ).addEventListener( "click" , () => this.accept() );
    Dom.get( "ais-reject" ).addEventListener( "click" , () => this.reject() );
    Dom.get( "ais-replay" ).addEventListener( "click" , () => this.replayInMatlab() );
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
    Dom.get( "ais-view-lock" ).addEventListener( "click" , () => this.setLocked( !this.locked ) );
    Dom.get( "ais-focus" ).addEventListener( "click" , () => this.setFocus( !this.focus ) );
    Dom.get( "ais-hint-close" ).addEventListener( "click" , () => this.setHint( false ) );
    Dom.get( "ais-hint-show" ).addEventListener( "click" , () => this.setHint( true ) );
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
    // back whatever the toolbar, file header or footer give up (closing the
    // instructions, a shorter file name, a narrower window).
    const around = new ResizeObserver( () => this.fitStage() );
    [ Dom.get( "ais-current" ) , document.querySelector( ".ais-layers" ) , document.querySelector( ".ais-toolbar" ) ]
      .forEach( ( element ) => around.observe( element ) );
    window.addEventListener( "resize" , () => this.fitStage() );
    window.addEventListener( "hashchange" , () => this.followUrl() );
    window.addEventListener( "popstate" , () => this.followUrl() );
    AisImages.init();
    AisExport.init();
    this.renderPicker();
    this.renderTable();
    this.renderViewTools();
    this.loadFocus();
    this.loadHint();
    this.resize();
    this.loadLocal();
    this.importLegacy().finally( () => this.followUrl() );
  },

  async loadLocal() {
    try {
      this.local = await Api.request( "/api/ais/local/status" );
    } catch ( error ) {
      this.local = { enabled: false , platform: "" , matlab: false };
    }
    Dom.show( Dom.get( "ais-open-path" ) , this.local.enabled );
    this.renderCurrent();
    this.renderResult();
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
  async followUrl() {
    if ( Nav.current() !== "ais" ) {
      if ( this.focus ) this.setFocus( false );
      return;
    }
    let want = this.parseUrl();
    let remembered = false;
    if ( !want ) {
      if ( this.batch ) { this.setUrl( false ); return; }
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
    if ( this.batch && this.batch.id === want.id ) {
      const i = this.images.findIndex( ( entry ) => entry.key === want.key );
      if ( i >= 0 && i !== this.index ) {
        if ( !this.images[ i ].included ) { this.images[ i ].included = true; this.renderPicker(); }
        this.show( i );
      }
      return;
    }
    try {
      const batch = await Api.request( "/api/ais/batches/" + want.id );
      await this.loadBatch( batch , null , { key: want.key } );
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

  // Picked in the browser (Open folder / Open files): hash every TIFF, create
  // the batch from names and hashes, then upload in the background.
  async openFiles( fileList ) {
    const files = Array.from( fileList ).filter( ( f ) => /\.tiff?$/i.test( f.name ) && !f.name.startsWith( "." ) );
    if ( !files.length ) {
      App.showError( I18n.get( "ais.no_tiffs" ) );
      return;
    }
    const rel = files[ 0 ].webkitRelativePath || "";
    const root = rel.includes( "/" ) ? rel.split( "/" )[ 0 ] : "";
    const name = root || I18n.get( "ais.loose_files" ) || "Files";
    const described = [];
    const byRel = new Map();
    try {
      for ( let i = 0; i < files.length; i += 1 ) {
        this.status( I18n.get( "ais.reading" ).replace( "{done}" , i + 1 ).replace( "{total}" , files.length ) );
        const f = files[ i ];
        const digest = await crypto.subtle.digest( "SHA-256" , await f.arrayBuffer() );
        const sha = Array.from( new Uint8Array( digest ) , ( b ) => b.toString( 16 ).padStart( 2 , "0" ) ).join( "" );
        const fileRel = f.webkitRelativePath || f.name;
        described.push( { name: f.name , rel: fileRel , sha: sha , size: f.size } );
        byRel.set( fileRel , f );
      }
      const batch = await Api.post( "/api/ais/batches/upload" , { name: name , files: described } );
      this.status( "" );
      await this.loadBatch( batch , byRel , { fresh: true } );
    } catch ( error ) {
      this.status( "" );
      App.showError( error.message );
    }
  },

  // Read by the server (Open path).
  async openPath( folder ) {
    this.status( I18n.get( "ais.reading_path" ) );
    try {
      const batch = await Api.post( "/api/ais/batches/path" , { path: folder } );
      this.status( "" );
      await this.loadBatch( batch , null , { fresh: true } );
    } catch ( error ) {
      this.status( "" );
      App.showError( error.message );
    }
  },

  // Show a server batch. byRel maps a file's folder-relative path to the
  // File picked in this browser (only right after Open folder / Open files).
  // options.key opens that image; options.fresh opens the Images dialog.
  async loadBatch( batch , byRel , options ) {
    const opts = options || {};
    this.batch = batch;
    // A newly opened set of images shows the single-image note again.
    if ( opts.fresh ) {
      try {
        window.localStorage.removeItem( this.noteKey );
      } catch ( error ) { /* storage blocked */ }
    }
    const excluded = this.savedExclusions( batch.id );
    this.images = batch.images.map( ( image ) => {
      const files = {};
      Object.entries( image.files ).forEach( ( [ role , f ] ) => {
        files[ role ] = Object.assign( {} , f , { file: byRel ? byRel.get( f.rel ) || null : null } );
      } );
      // A new import leaves duplicates out until they are shown again.
      const out = excluded ? excluded.has( image.key ) : ( opts.fresh && image.dup_of != null );
      return { key: image.key , cell: image.cell , dir: image.dir , dup_of: image.dup_of , files: files , included: !out };
    } );
    this.index = -1;
    this.source = null;
    this.bitmap = null;
    this.reject();
    Dom.get( "ais-table-scope" ).value = "batch";
    this.allRows = null;
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

  // Back to no batch (the open one was deleted).
  closeBatch() {
    this.uploadToken = null;
    this.batch = null;
    this.images = [];
    this.batchRows = [];
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

  savedExclusions( batchId ) {
    try {
      const raw = window.localStorage.getItem( this.includeKey + batchId );
      return raw ? new Set( JSON.parse( raw ) ) : null;
    } catch ( error ) {
      return null;
    }
  },

  saveExclusions() {
    if ( !this.batch ) return;
    try {
      window.localStorage.setItem( this.includeKey + this.batch.id ,
        JSON.stringify( this.images.filter( ( entry ) => !entry.included ).map( ( entry ) => entry.key ) ) );
    } catch ( error ) { /* storage blocked: the selection lasts this visit */ }
  },

  // The file that is thresholded and traced, and whether a separate raw
  // image exists to read the profile from.
  traced( entry ) {
    return entry.files.processed ? "processed" : "raw";
  },

  sha( entry , role ) {
    const f = entry.files[ role || this.traced( entry ) ];
    return f ? f.sha : null;
  },

  kind( entry ) {
    if ( entry.files.processed && entry.files.raw ) return "pair";
    return entry.files.processed ? "processed only" : "raw only";
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
    try {
      const out = await Api.post( "/api/ais/batches/" + this.batch.id + "/done" , { image: entry.key , done: marking } );
      this.batch.skipped = out.skipped;
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
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
    const select = Dom.get( "ais-image" );
    Dom.clear( select );
    const shown = this.included();
    Dom.text( Dom.get( "ais-images-count" ) , this.images.length ? shown.length + " / " + this.images.length : "" );
    Dom.get( "ais-images-open" ).disabled = !this.images.length;
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
      const single = this.kind( entry ) === "pair" ? "" : " (" + I18n.get( "ais.single" ) + ")";
      const label = mark + ( i + 1 ) + ". " + entry.key + single + ( count ? "  (" + count + ")" : "" );
      select.appendChild( Dom.el( "option" , { text: label , attrs: { value: String( i ) } } ) );
    } );
    select.value = String( shown.includes( this.index ) ? this.index : shown[ 0 ] );
    this.renderCurrent();
  },

  // Keep showing the current image while it is included; otherwise move to
  // the preferred image, or the nearest included one.
  inclusionChanged( prefer ) {
    this.saveExclusions();
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
    if ( next !== this.index ) this.show( next );
  },

  async show( index , push ) {
    this.index = index;
    this.result = null;
    this.lastBody = null;
    this.firstClick = null;
    this.renderResult();
    Dom.get( "ais-image" ).value = String( index );
    this.renderCurrent();
    this.setUrl( push );
    const entry = this.images[ index ];
    try {
      await this.upload( entry );
    } catch ( error ) {
      if ( this.index === index ) {
        this.source = null;
        this.bitmap = null;
        this.draw();
        this.status( error.message );
      }
      return;
    }
    if ( this.index !== index ) return;   // moved on while uploading
    const img = new Image();
    img.onload = () => {
      if ( this.index !== index ) return;
      this.source = img;
      this.buildBitmap();
      if ( !this.locked ) this.fit();
      Dom.show( Dom.get( "ais-empty" ) , false );
      this.status( this.imageNote( entry ) , true );
      this.draw();
    };
    img.onerror = () => { if ( this.index === index ) this.status( I18n.get( "ais.not_uploaded" ) ); };
    img.src = "/api/ais/files/" + this.sha( entry ) + "/view.png";
  },

  // Why a lone TIFF is handled the way it is -- until closed for this batch.
  imageNote( entry ) {
    const kind = this.kind( entry );
    if ( kind !== "pair" && this.noteHidden() ) return "";
    return kind === "pair" ? "" : I18n.get( kind === "raw only" ? "ais.raw_only" : "ais.no_raw" );
  },

  // Make sure the server has the image's files. Files picked in this browser
  // upload (once); Open-path files the server fetches itself; a file only
  // someone else has is "not uploaded yet" until they upload it.
  async upload( entry ) {
    for ( const role of [ "processed" , "raw" ] ) {
      const f = entry.files[ role ];
      if ( !f || f.stored ) continue;
      if ( !f.file ) throw new Error( I18n.get( "ais.not_uploaded" ) );
      if ( !f.pending ) {
        f.pending = ( async () => {
          await Api.post( "/api/ais/files" , { data: await this.base64( f.file ) } );
          // Every copy of the same bytes (duplicates) is on the server now.
          this.images.forEach( ( other ) => Object.values( other.files ).forEach( ( g ) => {
            if ( g.sha === f.sha ) g.stored = true;
          } ) );
        } )().finally( () => { f.pending = null; } );
      }
      await f.pending;
    }
  },

  // After an import: upload every included image this browser picked,
  // current first, one at a time, so the batch is complete for others.
  async uploadAll() {
    const token = {};
    this.uploadToken = token;
    const waiting = () => this.images.filter( ( entry ) => entry.included &&
      Object.values( entry.files ).some( ( f ) => !f.stored && f.file ) );
    const total = waiting().length;
    let done = 0;
    while ( this.uploadToken === token ) {
      const left = waiting();
      if ( !left.length ) break;
      const current = this.images[ this.index ];
      const next = left.includes( current ) ? current : left[ 0 ];
      Dom.text( Dom.get( "ais-upload-status" ) , I18n.get( "ais.uploading_n" ).replace( "{done}" , done ).replace( "{total}" , total ) );
      try {
        await this.upload( next );
      } catch ( error ) {
        App.showError( error.message );
        break;
      }
      done += 1;
    }
    if ( this.uploadToken === token ) Dom.text( Dom.get( "ais-upload-status" ) , "" );
  },

  base64( file ) {
    return new Promise( function ( resolve , reject ) {
      const reader = new FileReader();
      reader.onload = function () { resolve( String( reader.result ).split( "," )[ 1 ] || "" ); };
      reader.onerror = function () { reject( new Error( "could not read " + file.name ) ); };
      reader.readAsDataURL( file );
    } );
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
    Dom.text( Dom.get( "ais-progress-text" ) , I18n.get( "ais.completed" ).replace( "{done}" , done ).replace( "{total}" , total ) );
    Dom.get( "ais-progress-bar" ).style.width = ( total ? ( 100 * done / total ) : 0 ) + "%";
    Dom.get( "ais-progress-bar-wrap" ).setAttribute( "aria-valuenow" , String( done ) );
    Dom.get( "ais-progress-bar-wrap" ).setAttribute( "aria-valuemax" , String( total ) );
    const buttons = [ "ais-file-open" , "ais-file-reveal" , "ais-file-copy" , "ais-file-link" , "ais-matlab-menu" , "ais-file-done" ];
    Dom.show( Dom.get( "ais-matlab-group" ) , Boolean( this.local.matlab ) );
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
  async verifyInMatlab( entry , mode , clicks ) {
    if ( !entry || !this.local.matlab ) return;
    try {
      await this.upload( entry );
      await Api.post( "/api/ais/local/matlab" , {
        mode: mode || "run",
        processed: this.sha( entry ),
        raw: this.kind( entry ) === "pair" ? this.sha( entry , "raw" ) : null,
        cell: entry.cell,
        threshold: Settings.threshold(),
        settings: Settings.methodSettings(),
        clicks: clicks || null,
      } );
      Dom.toast( I18n.get( "ais.matlab_started" ) , "ok" );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // The clicks the shown trace used, in the order the original asks for them.
  replayInMatlab() {
    const r = this.result;
    const entry = this.images[ this.index ];
    if ( !r || !this.lastBody || !entry ) return;
    const clicks = [ this.lastBody.click ];
    if ( r.rethresholded ) clicks.push( this.lastBody.click2 || this.lastBody.click );
    this.verifyInMatlab( entry , "replay" , clicks );
  },

  // The preview is min..max scaled like imagesc; the brightness slider is a
  // display-only gamma on top, so faint AIS are easier to find.
  buildBitmap() {
    if ( !this.source ) return;
    const w = this.source.naturalWidth;
    const h = this.source.naturalHeight;
    const off = document.createElement( "canvas" );
    off.width = w;
    off.height = h;
    const octx = off.getContext( "2d" );
    octx.drawImage( this.source , 0 , 0 );
    const gamma = Number( Dom.get( "ais-gamma" ).value );
    if ( gamma !== 1 ) {
      const lut = new Uint8ClampedArray( 256 );
      for ( let v = 0; v < 256; v += 1 ) lut[ v ] = 255 * Math.pow( v / 255 , gamma );
      const data = octx.getImageData( 0 , 0 , w , h );
      const px = data.data;
      for ( let i = 0; i < px.length; i += 4 ) {
        px[ i ] = px[ i + 1 ] = px[ i + 2 ] = lut[ px[ i ] ];
      }
      octx.putImageData( data , 0 , 0 );
    }
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

  // The keyboard help under the image can be closed; a ? brings it back.
  setHint( shown ) {
    try {
      if ( shown ) window.localStorage.removeItem( this.hintKey );
      else window.localStorage.setItem( this.hintKey , "1" );
    } catch ( error ) { /* storage blocked: it just is not remembered */ }
    this.renderHint( shown );
  },

  loadHint() {
    let hidden = false;
    try {
      hidden = window.localStorage.getItem( this.hintKey ) === "1";
    } catch ( error ) { /* storage blocked */ }
    this.renderHint( !hidden );
  },

  renderHint( shown ) {
    Dom.show( Dom.get( "ais-hint" ) , shown );
    Dom.show( Dom.get( "ais-hint-show" ) , !shown );
    this.fitStage();
  },

  // Focus mode: the stage takes the window's height below the toolbar and
  // header, less the footer under it. Otherwise the stylesheet's height.
  fitStage() {
    const stage = Dom.get( "ais-stage" );
    if ( !this.focus || !stage.offsetParent ) {
      stage.style.height = "";
      return;
    }
    const top = stage.getBoundingClientRect().top + window.scrollY;
    const footer = document.querySelector( ".ais-layers" ).offsetHeight;
    const margin = 8;   // .ais-focus .app-main's bottom padding
    stage.style.height = Math.max( 240 , window.innerHeight - top - footer - margin ) + "px";
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
  // middle-drag always pans. Both stop while the view is locked.
  bindCanvas() {
    let down = null;
    this.canvas.addEventListener( "pointerdown" , ( e ) => {
      if ( e.button !== 0 && e.button !== 1 ) return;
      if ( e.button === 1 ) e.preventDefault();
      down = { x: e.clientX , y: e.clientY , ox: this.view.ox , oy: this.view.oy , moved: false , button: e.button };
      try { this.canvas.setPointerCapture( e.pointerId ); } catch ( error ) { /* pointer already gone */ }
    } );
    this.canvas.addEventListener( "pointermove" , ( e ) => {
      if ( !down ) return;
      const dx = e.clientX - down.x;
      const dy = e.clientY - down.y;
      if ( Math.abs( dx ) + Math.abs( dy ) > 4 ) down.moved = true;
      if ( down.moved && !this.locked ) {
        this.view.ox = down.ox + dx;
        this.view.oy = down.oy + dy;
        this.draw();
      }
    } );
    this.canvas.addEventListener( "pointerup" , ( e ) => {
      const wasClick = down && !down.moved && down.button === 0;
      down = null;
      if ( wasClick && e.button === 0 ) this.onClick( this.toImage( e ) );
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
    if ( event.ctrlKey || event.metaKey || event.altKey ) return;
    const key = event.key;
    const arrows = { ArrowLeft: [ -1 , 0 ] , ArrowRight: [ 1 , 0 ] , ArrowUp: [ 0 , -1 ] , ArrowDown: [ 0 , 1 ] };
    if ( arrows[ key ] && this.pending() ) {
      event.preventDefault();
      const step = event.shiftKey ? 5 : 1;
      this.nudge( arrows[ key ][ 0 ] * step , arrows[ key ][ 1 ] * step );
      return;
    }
    if ( key === "Enter" ) { event.preventDefault(); this.accept(); }
    else if ( key === "n" || key === "N" ) this.reject();
    else if ( key === "d" || key === "D" ) this.toggleDone();
    else if ( key === "ArrowRight" || key === "PageDown" ) { event.preventDefault(); this.step( 1 ); }
    else if ( key === "ArrowLeft" || key === "PageUp" ) { event.preventDefault(); this.step( -1 ); }
    else if ( key === "+" || key === "=" ) this.zoomBy( 1.25 );
    else if ( key === "-" || key === "_" ) this.zoomBy( 0.8 );
    else if ( key === "0" ) this.resetView();
    else if ( key === "1" ) this.zoomTo( 1 );
    else if ( key === "l" || key === "L" ) this.setLocked( !this.locked );
    else if ( key === "f" || key === "F" ) this.setFocus( !this.focus );
  },

  // --- tracing -------------------------------------------------------------

  onClick( point ) {
    const entry = this.images[ this.index ];
    if ( !entry || !this.bitmap ) return;
    if ( point.x < 0 || point.y < 0 || point.x >= this.bitmap.width || point.y >= this.bitmap.height ) return;
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
      } , body ) );
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
    Dom.show( Dom.get( "ais-replay" ) , Boolean( this.local.matlab ) );
    if ( !r ) return;
    const m = r.measures;
    Dom.text( Dom.get( "ais-length" ) , m ? m.length_str : I18n.get( "ais.no_length" ) );
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
    this.renderProfile( r.profile );
    Dom.get( "ais-accept" ).disabled = !( r.ok && !waitingForSecond );
    Dom.get( "ais-replay" ).disabled = !( r.path && !waitingForSecond );
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

  async accept() {
    const r = this.result;
    const entry = this.images[ this.index ];
    if ( !r || !r.ok || !entry || !this.batch || this.busy ) return;
    const m = r.measures;
    const traced = entry.files[ this.traced( entry ) ];
    const row = {
      file: traced.path || traced.rel || traced.name,
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
    };
    // The constants it was measured with (app/analysis/ais_auto.py Settings).
    AisExport.settingCols.forEach( ( key ) => { if ( key !== "smooth" ) row[ key ] = r.settings[ key ]; } );
    try {
      const saved = await Api.post( "/api/ais/results" , { batch_id: this.batch.id , image: entry.key , row: row } );
      this.batchRows.push( saved );
      if ( this.allRows ) this.allRows.push( saved );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    this.result = null;
    this.lastBody = null;
    this.renderResult();
    this.renderTable();
    this.renderPicker();
    this.draw();
  },

  reject() {
    this.result = null;
    this.lastBody = null;
    this.queuedBody = null;
    this.firstClick = null;
    this.status( "" );
    this.renderResult();
    this.draw();
  },

  // --- results (on the server) -------------------------------------------------

  async loadBatchRows() {
    if ( !this.batch ) {
      this.batchRows = [];
      return;
    }
    try {
      this.batchRows = ( await Api.request( "/api/ais/results?batch=" + this.batch.id ) ).results;
    } catch ( error ) {
      this.batchRows = [];
      App.showError( error.message );
    }
    this.renderTable();
  },

  async loadTable() {
    if ( Dom.get( "ais-table-scope" ).value === "all" ) {
      try {
        this.allRows = ( await Api.request( "/api/ais/results?batch=all" ) ).results;
      } catch ( error ) {
        App.showError( error.message );
      }
    }
    this.renderTable();
  },

  // The rows the table shows and the exports write: this batch's, or all.
  shownRows() {
    const all = Dom.get( "ais-table-scope" ).value === "all" || !this.batch;
    return all ? ( this.allRows || [] ) : this.batchRows;
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
        Dom.el( "td" , { text: row.length_str , class: "fw-semibold" } ),
        Dom.el( "td" , { text: this.fmt( row.start_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.end_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.max_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.threshold ) } ),
        Dom.el( "td" , { text: "(" + row.click_x + ", " + row.click_y + ")" } ),
        Dom.el( "td" , { text: row.source || "pair" } ),
        Dom.el( "td" , { text: row.batch_name || "" , class: "text-truncate ais-batch-name" } ),
        Dom.el( "td" , { children: [ del ] } ),
      ] } ) );
    } );
    Dom.get( "ais-export" ).disabled = !this.shownRows().length;
  },

  async deleteRow( row ) {
    try {
      await Api.post( "/api/ais/results/" + row.id + "/delete" , {} );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    this.batchRows = this.batchRows.filter( ( r ) => r.id !== row.id );
    if ( this.allRows ) this.allRows = this.allRows.filter( ( r ) => r.id !== row.id );
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
        const p = row.pixels[ 0 ];
        if ( p ) {
          ctx.fillStyle = "rgba(60, 220, 120, 1)";
          ctx.font = ( 12 / s ) + "px sans-serif";
          ctx.fillText( String( row.n ) , p[ 0 ] + 3 / s , p[ 1 ] - 3 / s );
        }
      } );
    }

    const r = this.result;
    if ( r ) {
      if ( r.component && this.layer( "component" ) ) this.dots( r.component.edge , "rgba(0, 200, 255, 0.55)" );
      if ( r.skeleton && this.layer( "skeleton" ) ) this.dots( r.skeleton , "rgba(255, 40, 40, 0.95)" );
      if ( r.pixels && this.layer( "trace" ) ) this.polyline( r.pixels , "rgba(40, 110, 255, 1)" , lw );
      if ( r.spline && this.layer( "spline" ) ) this.polyline( r.spline , "rgba(255, 225, 0, 1)" , lw );
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
