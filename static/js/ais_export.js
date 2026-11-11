// Exports of the accepted AIS the table shows (this batch, or all): the CSV on
// its own, or one ZIP holding the CSV and, per image, a full-resolution PNG
// with every accepted trace drawn and numbered as the Saved layer draws it.
// Rendering happens here from the server's preview of each image, so it
// works at any point in a batch. The Batches screen's reports (one batch or
// all) come from here too: an Excel workbook (xlsx.js), or a ZIP with it and
// what the Export dialog asks for -- the traced PNGs (as before), and as
// they are, as PNGs or both: the original files, the processed images and
// each channel found in the .czi files (16-bit TIFFs as they are); and
// (admins, blinded batches) either everything under its original names
// (unrandomize) or an Original-names folder of links to the files, with the
// batch's __Translation.txt either way.
const AisExport = {
  cols: [ "batch_name" , "batch_id" , "image" , "n" , "file" , "source" , "length_um" , "start_um" , "end_um" , "mid_um" , "max_um" , "arc_um" ,
    "threshold_initial" , "threshold" , "click_x" , "click_y" , "click2_x" , "click2_y" , "profile_points" ,
    "smooth" , "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ,
    "width_um" , "brightness" , "soma_um" , "soma_px" , "soma_ais_x" , "soma_ais_y" , "soma_x" , "soma_y" , "origin" , "accepted_at" , "edited_at" , "notes" ],
  // What a row measured on a Z-stack adds, at the end so nothing else moves,
  // and only when there are such rows (colsFor).
  zCols: [ "length_3d_um" , "length_xy_um" , "z_start" , "z_end" , "z_span_um" , "z_step_um" , "z_confidence" , "z_clipped" , "z_method" ],
  // The auto mode settings a row auto mode saved was found with (ais_auto.js
  // autoFields), after those, and only when there are such rows (colsFor).
  autoCols: [ "auto_method" , "auto_review" , "auto_start" , "auto_min_length" , "auto_min_length_shown" ,
    "auto_min_brightness" , "auto_min_contrast" , "auto_min_width" , "auto_max_soma_gap" , "auto_max_branchiness" , "auto_min_score" ],
  // A line the Measure tool recorded (Record): its own file and sheet, since it
  // is no AIS and an image may have them without having any AIS.
  measureCols: [ "batch_name" , "batch_id" , "image" , "n" , "type" , "label" , "length_um" , "length_px" , "a_x" , "a_y" , "b_x" , "b_y" ,
    "pixconv" , "created_at" , "edited_at" ],
  // The method settings each row was measured with; rows from before these
  // were saved leave them blank.
  settingCols: [ "smooth" , "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ],

  linkKey: "ais-export-links",
  bigBytes: 2 * 1024 * 1024 * 1024,
  retries: 5,
  // The address the Process screen shows a .czi's processed view at (ais.js
  // says why), not one a browser may hold an older copy under. A TIFF's view
  // is the same at any address.
  view: "view.png?processed=1&v=2",

  init() {
    Dom.get( "ais-export-csv" ).addEventListener( "click" , () => this.exportCsv() );
    Dom.get( "ais-export-zip" ).addEventListener( "click" , () => this.exportZip() );
    Dom.get( "ais-export-measurements" ).addEventListener( "click" , () => this.exportMeasurements() );
    this.optionsModal = bootstrap.Modal.getOrCreateInstance( Dom.get( "export-options-modal" ) );
    Dom.get( "export-options-table" ).addEventListener( "change" , ( e ) => this.tickColumn( e.target ) );
    Dom.get( "export-options-names" ).addEventListener( "change" , () => this.renderOptions() );
    Dom.get( "export-options-unrandomize" ).addEventListener( "change" , () => this.renderOptions() );
    Dom.get( "export-options-restorable" ).addEventListener( "change" , () => this.renderOptions() );
    Dom.get( "export-options-go" ).addEventListener( "click" , () => this.goOptions() );
  },

  // --- the Export dialog (a ZIP from the Batches screen) -------------------------

  // list: the batches (Batches rows), label for the dialog; onGo( options )
  // runs the export with { traces, originals, originalsPng, processed,
  // processedPng, channels, channelsPng (channel names), unrandomize,
  // names: null | "symlink" | "shortcut" | "copy", restorable, restorableFiles }.
  // Restorable (admins: it holds the original names) is on unless turned off.
  openOptions( list , label , onGo ) {
    this.optionsGo = onGo;
    Dom.text( Dom.get( "export-options-batch" ) , label );
    this.optionBoxes( "file" ).concat( this.optionBoxes( "png" ) ).forEach( ( box ) => {
      box.checked = box.id === "export-options-traces";
    } );
    Dom.get( "export-options-channels" ).replaceChildren();
    const blinded = Batches.admin() && list.some( ( b ) => b.randomized );
    Dom.show( Dom.get( "export-options-blind" ) , blinded );
    Dom.get( "export-options-names" ).checked = false;
    Dom.get( "export-options-unrandomize" ).checked = false;
    Dom.show( Dom.get( "export-options-backup" ) , Batches.admin() );
    Dom.get( "export-options-restorable" ).checked = true;
    Dom.get( "export-options-restorable-files" ).checked = true;
    let links = null;
    try {
      links = window.localStorage.getItem( this.linkKey );
    } catch ( error ) { /* storage blocked: the default */ }
    Dom.get( "export-options-links" ).value = links || this.defaultLinks();
    this.renderOptions();
    this.optionsModal.show();
    this.loadChannels( list );
  },

  // The boxes of a column of the dialog: "file" (Original) or "png".
  optionBoxes( kind ) {
    return Array.from( Dom.get( "export-options-table" ).querySelectorAll( "tbody .export-" + kind ) );
  },

  // A column's header box ticks the whole column.
  tickColumn( box ) {
    const kind = { "export-options-all-file": "file" , "export-options-all-png": "png" }[ box.id ];
    if ( kind ) this.optionBoxes( kind ).forEach( ( b ) => { b.checked = box.checked; } );
    this.renderOptions();
  },

  channelNote( text ) {
    const note = Dom.get( "export-options-channels-note" );
    Dom.text( note , text );
    Dom.show( note , Boolean( text ) );
  },

  // A row per channel name found in these batches; the dialog works without
  // them until they come, and a reply for an earlier opening is dropped.
  async loadChannels( list ) {
    this.optionsToken = ( this.optionsToken || 0 ) + 1;
    const token = this.optionsToken;
    this.channelNote( I18n.get( "batches.export_channels_looking" ) );
    let found = null;
    try {
      found = await Promise.all( list.map( ( b ) => Api.request( "/api/ais/batches/" + b.id + "/channels" ) ) );
    } catch ( error ) { /* said below */ }
    if ( token !== this.optionsToken ) return;
    if ( !found ) {
      this.channelNote( I18n.get( "batches.export_channels_failed" ) );
      return;
    }
    const channels = new Map();
    found.forEach( ( batch ) => batch.channels.forEach( ( c ) => {
      if ( channels.has( c.name ) ) channels.get( c.name ).files += c.files;
      else channels.set( c.name , Object.assign( {} , c ) );
    } ) );
    const total = found.reduce( ( sum , batch ) => sum + batch.czis , 0 );
    const unread = found.reduce( ( sum , batch ) => sum + batch.unread , 0 );
    this.renderChannels( Array.from( channels.values() ) , total );
    if ( unread ) this.channelNote( I18n.get( "batches.export_channels_unread" ).replace( "{n}" , unread ) );
    else this.channelNote( channels.size ? "" : I18n.get( "batches.export_channels_none" ) );
  },

  // New rows follow a column already ticked as a whole.
  renderChannels( channels , total ) {
    const box = ( c , kind ) => {
      const input = Dom.el( "input" , { class: "form-check-input export-" + kind ,
        attrs: { type: "checkbox" , "data-channel": c.name , "aria-label": c.name } } );
      input.checked = Dom.get( "export-options-all-" + kind ).checked;
      return Dom.el( "td" , { class: "text-center" , children: [ input ] } );
    };
    const row = ( c ) => {
      // The dot's color through the DOM: the CSP has no inline style attributes.
      const dot = Dom.el( "span" , { class: "ais-channel-dot me-1" } );
      dot.style.backgroundColor = c.color;
      const count = I18n.get( "batches.export_channel_count" ).replace( "{n}" , c.files ).replace( "{total}" , total );
      return Dom.el( "tr" , { children: [
        Dom.el( "td" , { children: [ dot , Dom.el( "span" , { text: c.name } ) ,
          Dom.el( "span" , { class: "small text-body-secondary ms-2" , text: count } ) ] } ),
        box( c , "file" ) , box( c , "png" ),
      ] } );
    };
    const heading = Dom.el( "tr" , { children: [ Dom.el( "th" , { class: "small text-body-secondary fw-normal" ,
      text: I18n.get( "batches.export_channels" ) , attrs: { colspan: "3" , scope: "colgroup" } } ) ] } );
    Dom.get( "export-options-channels" ).replaceChildren( ...( channels.length ? [ heading ].concat( channels.map( row ) ) : [] ) );
    this.renderOptions();
  },

  // Shortcuts for a Windows computer, symbolic links for the others.
  defaultLinks() {
    const platform = ( navigator.userAgentData && navigator.userAgentData.platform ) || navigator.platform || "";
    return /win/i.test( platform ) ? "shortcut" : "symlink";
  },

  // Under the original names, a folder of links to them has nothing to add.
  renderOptions() {
    const unrandomize = Dom.get( "export-options-unrandomize" ).checked;
    Dom.get( "export-options-names" ).disabled = unrandomize;
    Dom.get( "export-options-links" ).disabled = unrandomize || !Dom.get( "export-options-names" ).checked;
    const restorable = Dom.get( "export-options-restorable" ).checked;
    Dom.get( "export-options-restorable-files" ).disabled = !restorable;
    Dom.show( Dom.get( "export-options-restorable-warning" ) , !restorable );
    [ "file" , "png" ].forEach( ( kind ) => {
      const boxes = this.optionBoxes( kind );
      const ticked = boxes.filter( ( box ) => box.checked ).length;
      const all = Dom.get( "export-options-all-" + kind );
      all.checked = ticked === boxes.length;
      all.indeterminate = ticked > 0 && ticked < boxes.length;
    } );
  },

  goOptions() {
    const checked = ( key ) => Dom.get( "export-options-" + key ).checked;
    const blinded = !Dom.get( "export-options-blind" ).hidden;
    const links = Dom.get( "export-options-links" ).value;
    try {
      window.localStorage.setItem( this.linkKey , links );
    } catch ( error ) { /* storage blocked */ }
    const unrandomize = blinded && checked( "unrandomize" );
    const restorable = !Dom.get( "export-options-backup" ).hidden && checked( "restorable" );
    const channels = ( kind ) => this.optionBoxes( kind ).filter( ( box ) => box.checked && box.dataset.channel )
      .map( ( box ) => box.dataset.channel );
    const options = { traces: checked( "traces" ) , originals: checked( "originals" ) , originalsPng: checked( "originals-png" ) ,
      processed: checked( "processed" ) , processedPng: checked( "processed-png" ) , channels: channels( "file" ) , channelsPng: channels( "png" ) ,
      unrandomize: unrandomize , names: blinded && !unrandomize && checked( "names" ) ? links : null ,
      restorable: restorable , restorableFiles: restorable && checked( "restorable-files" ) };
    this.optionsToken = ( this.optionsToken || 0 ) + 1;
    this.optionsModal.hide();
    if ( this.optionsGo ) this.optionsGo( options );
  },

  colsFor( rows ) {
    let cols = rows.some( ( row ) => row.z_method ) ? this.cols.concat( this.zCols ) : this.cols;
    if ( rows.some( ( row ) => row.auto_method ) ) cols = cols.concat( this.autoCols );
    return cols;
  },

  csv( rows ) {
    return this.table( this.colsFor( rows ) , rows );
  },

  measurementsCsv( lines ) {
    return this.table( this.measureCols , lines );
  },

  // Extra files for a ZIP: measurements.csv, when there are any.
  measurementFiles( lines ) {
    return lines.length ? [ { name: "measurements.csv" , data: this.measurementsCsv( lines ) } ] : [];
  },

  table( cols , rows ) {
    const quote = ( v ) => {
      const s = v == null ? "" : String( v );
      return /[",\n]/.test( s ) ? '"' + s.replace( /"/g , '""' ) + '"' : s;
    };
    return [ cols.join( "," ) ].concat( rows.map( ( row ) => cols.map( ( c ) => quote( row[ c ] ) ).join( "," ) ) ).join( "\n" ) + "\n";
  },

  // "ais_<batch>_<yyyy-mm-dd>" for the current batch, "ais_<batch>_<image>_<date>"
  // for the image on screen, "ais_all_<date>" otherwise.
  baseName() {
    const scope = Dom.get( "ais-table-scope" ).value;
    const all = scope === "all" || !Ais.batch;
    const entry = Ais.images[ Ais.index ];
    const label = all ? "all" : scope === "image" && entry ? Ais.batch.name + "_" + entry.key : Ais.batch.name;
    return "ais_" + this.safe( label ) + "_" + new Date().toISOString().slice( 0 , 10 );
  },

  safe( text ) {
    return String( text ).replace( /[^A-Za-z0-9._-]+/g , "_" ).replace( /^_+|_+$/g , "" ) || "images";
  },

  download( blob , name ) {
    const link = Dom.el( "a" , { attrs: { href: URL.createObjectURL( blob ) , download: name } } );
    document.body.appendChild( link );
    link.click();
    link.remove();
    window.setTimeout( () => URL.revokeObjectURL( link.href ) , 10000 );
  },

  exportCsv() {
    const rows = Ais.shownRows();
    if ( !rows.length ) return;
    this.download( new Blob( [ this.csv( rows ) ] , { type: "text/csv" } ) , this.baseName() + ".csv" );
  },

  exportMeasurements() {
    const lines = Ais.shownMeasurements();
    if ( !lines.length ) return;
    this.download( new Blob( [ this.measurementsCsv( lines ) ] , { type: "text/csv" } ) , this.baseName() + "_measurements.csv" );
  },

  exportZip() {
    const rows = Ais.shownRows();
    const lines = Ais.shownMeasurements();
    if ( !rows.length && !lines.length ) return;
    return this.zip( rows , this.baseName() , ( done , total ) => Ais.status( total
      ? I18n.get( "ais.exporting" ).replace( "{done}" , done ).replace( "{total}" , total ) : "" ) , this.measurementFiles( lines ) );
  },

  // The ZIP: results.csv, extra (more files, e.g. a batch report) and, with
  // traces (the default), one PNG per image, rows grouped by batch and image.
  // progress( done , total ) per image, then ( 0 , 0 ) when done.
  async zip( rows , base , progress , extra , traces ) {
    const groups = new Map();
    rows.forEach( ( row ) => {
      const key = row.batch_id + "\n" + row.image;
      if ( !groups.has( key ) ) groups.set( key , [] );
      groups.get( key ).push( row );
    } );
    const multiBatch = new Set( rows.map( ( row ) => row.batch_id ) ).size > 1;
    const files = [ { name: "results.csv" , data: this.csv( rows ) } ].concat( extra || [] );
    // A few images at a time, each put back in its place once drawn.
    const list = traces === false ? [] : Array.from( groups.values() );
    const pngs = new Array( list.length );
    const missing = new Array( list.length );
    let done = 0;
    progress( 0 , list.length );
    await Ais.pool( list , Ais.concurrency , async ( group , i ) => {
      const first = group[ 0 ];
      try {
        const sha = await this.shaFor( first );
        if ( !sha ) throw new Error( "image not available" );
        const png = await this.render( sha , group );
        const folder = multiBatch ? this.safe( first.batch_name || "batch" ) + "/" : "";
        pngs[ i ] = { name: folder + this.safe( first.image.replace( /\//g , "__" ) ) + "_traces.png" , data: png };
      } catch ( error ) {
        missing[ i ] = ( first.batch_name ? first.batch_name + " / " : "" ) + first.image + ": " + error.message;
      }
      done += 1;
      progress( done , list.length );
    } );
    pngs.forEach( ( png ) => { if ( png ) files.push( png ); } );
    const gone = missing.filter( Boolean );
    if ( gone.length ) files.push( { name: "missing.txt" , data: gone.join( "\n" ) + "\n" } );
    progress( 0 , 0 );
    this.download( Zip.build( files ) , base + ".zip" );
  },

  // --- batch reports (the Batches screen) ------------------------------------------

  // One image's state, most telling first: [ key , badge tone ].
  imageState( image ) {
    if ( image.dup_of != null ) return [ "duplicate" , "secondary" ];
    if ( image.stored < image.files ) return [ "not_uploaded" , "warning" ];
    if ( image.done ) return [ "done" , "success" ];
    if ( image.ais && image.auto === image.ais ) return [ "auto" , "info" ];
    if ( image.ais ) return [ "accepted" , "success" ];
    return [ "waiting" , "light" ];
  },

  // n, mean, median, SD (sample), min and max of the numbers in values,
  // rounded to 3 decimals; blanks when there are none.
  stats( values ) {
    const v = values.filter( ( x ) => typeof x === "number" && Number.isFinite( x ) ).sort( ( a , b ) => a - b );
    const round = ( x ) => Math.round( x * 1000 ) / 1000;
    if ( !v.length ) return { n: 0 , mean: null , median: null , sd: null , min: null , max: null };
    const mean = v.reduce( ( a , b ) => a + b , 0 ) / v.length;
    const mid = Math.floor( v.length / 2 );
    const median = v.length % 2 ? v[ mid ] : ( v[ mid - 1 ] + v[ mid ] ) / 2;
    const sd = v.length > 1 ? Math.sqrt( v.reduce( ( a , b ) => a + ( b - mean ) ** 2 , 0 ) / ( v.length - 1 ) ) : null;
    return { n: v.length , mean: round( mean ) , median: round( median ) , sd: sd == null ? null : round( sd ) ,
      min: round( v[ 0 ] ) , max: round( v[ v.length - 1 ] ) };
  },

  header( keys ) {
    return keys.map( ( key ) => I18n.get( "report." + key ) || key );
  },

  // items: [{ batch (a /api/ais/batches row), images (its /status), rows (its
  // accepted AIS) }] -> the report's sheets: a summary line per batch, a line
  // per image, per assignee, and every accepted AIS as the CSV has it.
  sheets( items ) {
    const date = ( iso ) => iso ? new Date( iso ).toLocaleString() : "";
    const summary = items.map( ( { batch: b , images: list , rows } ) => {
      const s = this.stats( rows.map( ( r ) => r.length_um ) );
      return [ b.name , b.id , b.created_by_name || "" , date( b.created_at ) , b.archived_at ? date( b.archived_at ) : "" ,
        ( list || [] ).length , b.completed , b.duplicates || 0 , rows.length , s.mean , s.median , s.sd , s.min , s.max ,
        b.completed ? Math.round( 1000 * rows.length / b.completed ) / 1000 : null ];
    } );
    const images = [];
    items.forEach( ( { batch: b , images: list , rows } ) => {
      const byImage = new Map();
      rows.forEach( ( r ) => {
        if ( !byImage.has( r.image ) ) byImage.set( r.image , [] );
        byImage.get( r.image ).push( r.length_um );
      } );
      ( list || [] ).forEach( ( image ) => {
        const s = this.stats( byImage.get( image.key ) || [] );
        images.push( [ b.name , image.key , I18n.get( "batches.state_" + this.imageState( image )[ 0 ] ) , image.ais , s.mean , s.median ,
          image.assignee_name || "" ] );
      } );
    } );
    const assignees = [];
    items.forEach( ( { batch: b } ) => ( b.assignees || [] ).forEach( ( a ) => assignees.push( [
      b.name , a.name || "" , a.images , a.completed , Math.round( a.percent ) , a.ais , date( a.last_at ) ] ) ) );
    const ais = [];
    const aisCols = this.colsFor( items.flatMap( ( { rows } ) => rows ) );
    items.forEach( ( { rows } ) => rows.forEach( ( row ) => ais.push( aisCols.map( ( c ) => row[ c ] ) ) ) );
    const lines = items.flatMap( ( item ) => item.measurements || [] ).map( ( line ) => this.measureCols.map( ( c ) => line[ c ] ) );
    const measured = lines.length ? [ { name: I18n.get( "report.sheet_measurements" ) , rows: lines , cols: this.measureCols } ,
      { name: I18n.get( "report.sheet_types" ) , rows: this.typeRows( items ) ,
        cols: this.header( [ "batch" , "image" , "type" , "count" , "mean_type_um" , "median_type_um" , "sd_type_um" ] ) } ] : [];
    return [
      { name: I18n.get( "report.sheet_summary" ) , rows: summary , cols: this.header( [ "batch" , "batch_id" , "opened_by" , "created" , "archived" ,
        "images" , "completed" , "duplicates" , "ais" , "mean_um" , "median_um" , "sd_um" , "min_um" , "max_um" , "ais_per_image" ] ) },
      { name: I18n.get( "report.sheet_images" ) , rows: images , cols: this.header( [ "batch" , "image" , "state" , "ais" , "mean_um" , "median_um" , "assignee" ] ) },
      { name: I18n.get( "report.sheet_assignees" ) , rows: assignees , cols: this.header( [ "batch" , "person" , "images" , "completed" , "percent" , "ais" , "last_activity" ] ) },
      { name: I18n.get( "report.sheet_ais" ) , rows: ais , cols: aisCols },
    ].concat( measured );
  },

  // The recorded lines per batch, image and type: how many, and their
  // length. Lines with no type count under "(no type)".
  typeRows( items ) {
    const groups = new Map();
    items.forEach( ( { batch: b , measurements } ) => ( measurements || [] ).forEach( ( line ) => {
      const type = line.type || I18n.get( "ais.measure_type_none" );
      const key = JSON.stringify( [ b.id , line.image , type ] );
      if ( !groups.has( key ) ) groups.set( key , { batch: b.name , image: line.image , type: type , lengths: [] } );
      groups.get( key ).lengths.push( line.length_um );
    } ) );
    return [ ...groups.values() ].map( ( g ) => {
      const s = this.stats( g.lengths );
      return [ g.batch , g.image , g.type , s.n , s.mean , s.median , s.sd ];
    } );
  },

  sheetCsv( sheet ) {
    const quote = ( v ) => {
      const s = v == null ? "" : String( v );
      return /[",\n]/.test( s ) ? '"' + s.replace( /"/g , '""' ) + '"' : s;
    };
    return [ sheet.cols ].concat( sheet.rows ).map( ( row ) => row.map( quote ).join( "," ) ).join( "\n" ) + "\n";
  },

  // "xlsx": the report on its own; "zip": the report, its summary as CSV,
  // results.csv, the traced PNGs and the files options asks for (see
  // openOptions; none given: the traces only). With restorable it can also
  // be imported back (backupFiles).
  async exportReport( items , label , kind , report , options ) {
    let at = [ 0 , 0 ];
    const progress = ( done , total ) => {
      at = [ done , total ];
      report( done , total );
    };
    this.onWait = () => report( at[ 0 ] , at[ 1 ] , true );
    try {
      await this.buildReport( items , label , kind , progress , options );
    } finally {
      this.onWait = null;
    }
  },

  async buildReport( items , label , kind , progress , options ) {
    const base = "ais_" + this.safe( label ) + "_" + new Date().toISOString().slice( 0 , 10 );
    const opts = options || { traces: true };
    if ( opts.unrandomize ) items = await this.unrandomized( items );
    // Admins: the original names and the groups by treatment (compare.js);
    // not in a backup made before a reset, which asks nothing.
    const sheets = this.sheets( items ).concat( opts.grouped === false ? [] : await Compare.extraSheets( items ) );
    const workbook = Xlsx.build( sheets );
    if ( kind === "xlsx" ) {
      this.download( workbook , base + ".xlsx" );
      return;
    }
    const rows = items.flatMap( ( item ) => item.rows );
    const files = await this.imageFiles( items , opts , progress );
    if ( files === null ) return;
    const backup = opts.restorable ? await this.backupFiles( items.map( ( item ) => item.batch ) , opts.restorableFiles , progress ) :
      { files: [] , failed: 0 };
    await this.zip( rows , base , progress , [
      { name: "report.xlsx" , data: new Uint8Array( await workbook.arrayBuffer() ) },
      { name: "summary.csv" , data: this.sheetCsv( sheets[ 0 ] ) },
    ].concat( this.measurementFiles( items.flatMap( ( item ) => item.measurements || [] ) ) , files , backup.files ) , opts.traces !== false );
    if ( backup.failed ) App.showError( I18n.get( "batches.backup_failed" ).replace( "{n}" , backup.failed ) );
  },

  // items with every blinded image and file under what it was called before
  // (admins see that in the batch: original_key, a file's original), so the
  // report, results.csv and the traced PNGs use those names; each item keeps
  // its whole batch as full for imageFiles. Images with no original name
  // keep the random one. A row keeps its random key as random_image (shaFor).
  async unrandomized( items ) {
    return Promise.all( items.map( async ( item ) => {
      const full = await Api.request( "/api/ais/batches/" + item.batch.id );
      const keys = new Map();
      const files = new Map();
      full.images.forEach( ( image ) => {
        if ( image.original_key ) keys.set( image.key , image.original_key );
        Object.values( image.files ).forEach( ( f ) => {
          if ( !f.original ) return;
          files.set( f.name , f.original.name );
          files.set( f.rel , f.original.rel );
        } );
      } );
      return Object.assign( {} , item , {
        full: full,
        images: ( item.images || [] ).map( ( image ) => Object.assign( {} , image , { key: keys.get( image.key ) || image.key } ) ),
        rows: item.rows.map( ( row ) => Object.assign( {} , row , { random_image: row.image , image: keys.get( row.image ) || row.image ,
          file: files.get( row.file ) || row.file } ) ),
        measurements: ( item.measurements || [] ).map( ( line ) => Object.assign( {} , line , { image: keys.get( line.image ) || line.image } ) ),
      } );
    } ) );
  },

  // --- backups -----------------------------------------------------------------------

  // What makes a ZIP one a batch can be rebuilt from (Batches.importBackup):
  // manifest.json with each batch's record and results (app/models/ais.py),
  // whole whatever the report leaves out, and with withFiles each stored file
  // once, under its sha. Returns { files , failed }: failed counts the files
  // the server does not have or could not hand over.
  async backupFiles( list , withFiles , progress ) {
    const parts = [];
    for ( const b of list ) parts.push( await Api.request( "/api/ais/batches/" + b.id + "/backup" ) );
    const stored = new Set( parts.flatMap( ( part ) => part.stored ) );
    const entries = new Map();   // zip name -> url
    const absent = new Set();
    parts.forEach( ( part ) => part.batch.images.forEach( ( image ) => Object.entries( image.files ).forEach( ( [ role , file ] ) => {
      ( file.slices || [ file ] ).forEach( ( f ) => {
        if ( !stored.has( f.sha ) ) {
          absent.add( f.sha );
        } else {
          entries.set( "files/" + f.sha + ( role === "czi" ? ".czi" : ".tif" ) , "/api/ais/files/" + f.sha + "/file" );
        }
      } );
    } ) ) );
    const files = [];
    let failed = 0;
    if ( withFiles ) {
      failed = absent.size;
      let done = 0;
      for ( const [ name , url ] of entries ) {
        progress( done , entries.size );
        try {
          files.push( { name: name , data: await this.bytes( url ) } );
        } catch ( error ) {
          failed += 1;
        }
        done += 1;
      }
    }
    const users = Object.assign( {} , ...parts.map( ( part ) => part.users ) );
    const manifest = { format: parts[ 0 ].format , version: parts[ 0 ].version , exported_at: new Date().toISOString() ,
      users: users , batches: parts.map( ( part ) => ( { batch: part.batch , results: part.results , measurements: part.measurements } ) ) };
    files.unshift( { name: "manifest.json" , data: JSON.stringify( manifest ) } );
    return { files: files , failed: failed };
  },

  // --- the image files of a ZIP ------------------------------------------------------

  // A long export can outrun the server's request limit: wait as it says, and
  // try again.
  async bytes( url ) {
    let response = await fetch( url , { credentials: "same-origin" } );
    for ( let tries = 0 ; response.status === 429 && tries < this.retries ; tries += 1 ) {
      if ( this.onWait ) this.onWait();
      const seconds = Number( response.headers.get( "retry-after" ) ) || 60;
      await new Promise( ( resolve ) => window.setTimeout( resolve , seconds * 1000 ) );
      response = await fetch( url , { credentials: "same-origin" } );
    }
    if ( !response.ok ) {
      let message = response.statusText;
      try {
        message = ( await response.json() ).error || message;
      } catch ( error ) { /* not JSON */ }
      throw new Error( message );
    }
    return new Uint8Array( await response.arrayBuffer() );
  },

  // What to fetch for one image: [{ folder, name, url, size }] -- originals:
  // its .czi, or its raw TIFF (or the processed one when that is all there
  // is); processed: a pair's processed TIFF, a .czi's processed AIS channel;
  // channels: the .czi's channels named. Each with a PNG of it in a folder of
  // its own if asked (a .czi's original: its channels merged). fail( error )
  // when its channels cannot be listed: the rest of it still goes.
  async planImage( image , opts , fail ) {
    const out = [];
    const f = image.files;
    const url = ( sha , tail ) => "/api/ais/files/" + sha + "/" + tail;
    const file = ( folder , x ) => out.push( { folder: folder , name: x.name , url: url( x.sha , "file" ) , size: x.size || 0 } );
    const png = ( folder , name , address ) => out.push( { folder: folder , name: name , url: address , size: 0 } );
    if ( f.stack ) {
      // Named from the image, as a blinded stack's slices come without theirs.
      if ( opts.originals ) {
        f.stack.slices.forEach( ( s ) => file( "originals" , { name: image.cell + "_z" + String( s.z ).padStart( 3 , "0" ) + ".tif" , sha: s.sha , size: s.size } ) );
      }
      if ( opts.originalsPng ) png( "originals_png" , image.cell + ".png" , url( f.stack.sha , "composite.png" ) );
      if ( opts.processedPng ) png( "processed_png" , image.cell + "_processed.png" , url( f.stack.sha , "view.png" ) );
      if ( opts.processed ) png( "processed" , image.cell + Ais.processedSuffix , url( f.stack.sha , "processed.tif" ) );
      return out;
    }
    const original = f.czi || f.raw || f.processed;
    if ( opts.originals && original ) file( "originals" , original );
    if ( opts.originalsPng && original ) {
      png( "originals_png" , image.cell + ".png" , url( original.sha , f.czi ? "composite.png" : "view.png" ) );
    }
    if ( opts.processedPng ) {
      const name = image.cell + "_processed.png";
      if ( f.czi ) png( "processed_png" , name , url( Ais.sha( image , "czi" ) , this.view ) );   // its AIS channel, as chosen
      else if ( f.processed && f.raw ) png( "processed_png" , name , url( f.processed.sha , "view.png" ) );
    }
    if ( opts.processed ) {
      if ( f.czi ) {
        out.push( { folder: "processed" , name: image.cell + Ais.processedSuffix , url: "/api/ais/files/" + Ais.sha( image , "czi" ) + "/processed.tif" ,
          size: f.czi.size || 0 } );
      } else if ( f.processed && f.raw ) {
        file( "processed" , f.processed );
      }
    }
    const tiffs = new Set( opts.channels || [] );
    const pngs = new Set( opts.channelsPng || [] );
    if ( ( tiffs.size || pngs.size ) && f.czi ) {
      try {
        const listed = await this.bytes( url( f.czi.sha , "channels" ) );
        JSON.parse( new TextDecoder().decode( listed ) ).channels.forEach( ( c , i ) => {
          const name = image.cell + "_c" + ( i + 1 ) + "_" + this.safe( c.name );
          if ( tiffs.has( c.name ) ) png( "channels" , name + ".tif" , url( f.czi.sha , "channel/" + c.index + ".tif" ) );
          if ( pngs.has( c.name ) ) png( "channels_png" , name + ".png" , url( f.czi.sha , "channel/" + c.index + ".png" ) );
        } );
      } catch ( error ) {
        fail( error );
      }
    }
    return out;
  },

  // The ZIP entries of every included image's files, in a folder per batch
  // when there are several, each kind of file in its own folder, under their
  // original names with unrandomize; with names, an "original names" folder
  // pointing at them. __Translation.txt with either; missing_files.txt when
  // some could not be had. null when it would be too big and the person says
  // not to go on.
  async imageFiles( items , opts , progress ) {
    const wantFiles = opts.originals || opts.originalsPng || opts.processed || opts.processedPng ||
      ( opts.channels || [] ).length || ( opts.channelsPng || [] ).length;
    if ( !wantFiles && !opts.unrandomize ) return [];
    const multi = items.length > 1;
    const plan = [];
    const extra = [];
    const missing = [];
    for ( const item of items ) {
      const prefix = multi ? this.safe( item.batch.name ) + "/" : "";
      const batch = item.full || await Api.request( "/api/ais/batches/" + item.batch.id );
      const excluded = new Set( batch.excluded || [] );
      for ( const image of wantFiles ? batch.images : [] ) {
        if ( excluded.has( image.key ) ) continue;
        // A blinded stack's folder went with its name, and comes back with it.
        const folder = opts.unrandomize && image.original_dir || image.dir;
        const dir = folder ? folder + "/" : "";
        const shown = prefix + ( opts.unrandomize && image.original_key || image.key );
        const fail = ( error ) => missing.push( shown + ": " + error.message );
        ( await this.planImage( image , opts , fail ) ).forEach( ( p ) => {
          if ( opts.unrandomize && image.original_cell && p.name.startsWith( image.cell ) ) {
            p.name = image.original_cell + p.name.slice( image.cell.length );
          }
          plan.push( Object.assign( p , { prefix: prefix , dir: dir , image: image } ) );
        } );
      }
      if ( ( opts.names || opts.unrandomize ) && batch.images.some( ( image ) => image.original_key ) ) {
        extra.push( { name: prefix + "__Translation.txt" , data: await this.bytes( "/api/ais/batches/" + batch.id + "/translation.txt" ) } );
      }
    }
    const total = plan.reduce( ( sum , p ) => sum + p.size , 0 ) * ( opts.names === "copy" ? 2 : 1 );
    if ( total > this.bigBytes && !window.confirm( I18n.get( "batches.export_big" ).replace( "{size}" , AisImages.size( total ) ) ) ) return null;
    const files = new Array( plan.length );
    let done = 0;
    progress( 0 , plan.length );
    await Ais.pool( plan , Ais.concurrency , async ( p , i ) => {
      const name = p.prefix + p.folder + "/" + p.dir + p.name;
      try {
        files[ i ] = { name: name , data: await this.bytes( p.url ) };
      } catch ( error ) {
        missing.push( name + ": " + error.message );
      }
      done += 1;
      progress( done , plan.length );
    } );
    const out = files.filter( Boolean );
    if ( opts.names ) {
      plan.forEach( ( p , i ) => {
        const image = p.image;
        if ( !files[ i ] || !image.original_key || !p.name.startsWith( image.cell ) ) return;
        const original = image.original_cell + p.name.slice( image.cell.length );
        // From original names/<folder>/<dir> back up to the batch's top.
        const depth = 2 + ( p.dir ? p.dir.split( "/" ).length - 1 : 0 );
        const target = "../".repeat( depth ) + p.folder + "/" + p.dir + p.name;
        const at = p.prefix + "original names/" + p.folder + "/" + p.dir + original;
        if ( opts.names === "symlink" ) out.push( { name: at , data: target , link: true } );
        else if ( opts.names === "shortcut" ) out.push( { name: at + ".lnk" , data: Lnk.build( target ) } );
        else out.push( { name: at , data: files[ i ].data } );
      } );
    }
    if ( missing.length ) extra.push( { name: "missing_files.txt" , data: missing.join( "\n" ) + "\n" } );
    return out.concat( extra );
  },

  // The traced image's id on the server, stored with the row. If this
  // browser picked that image and has not uploaded it yet, it does now.
  async shaFor( row ) {
    const key = row.random_image || row.image;
    const entry = Ais.batch && row.batch_id === Ais.batch.id ? Ais.images.find( ( e ) => e.key === key ) : null;
    if ( entry ) await Ais.upload( entry );
    return row.sha || ( entry ? Ais.sha( entry ) : null );
  },

  async render( sha , rows ) {
    // Through bytes(), for its waiting: the files before these may have used
    // up the request limit.
    const data = await this.bytes( "/api/ais/files/" + sha + "/" + this.view );
    const img = await createImageBitmap( new Blob( [ data ] , { type: "image/png" } ) );
    const canvas = document.createElement( "canvas" );
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext( "2d" );
    ctx.drawImage( img , 0 , 0 );
    const unit = Math.max( 1 , Math.max( canvas.width , canvas.height ) / 700 );
    ctx.font = "bold " + Math.round( 12 * unit ) + "px sans-serif";
    rows.forEach( ( row ) => {
      Ais.polyline( row.pixels , Settings.traceColor( 0.95 ) , Settings.lineWidth() * unit , ctx );
      const p = row.pixels && row.pixels[ 0 ];
      if ( p ) {
        ctx.lineWidth = 3 * unit;
        ctx.strokeStyle = "rgba(0, 0, 0, 0.8)";
        ctx.strokeText( String( row.n ) , p[ 0 ] + 3 * unit , p[ 1 ] - 3 * unit );
        ctx.fillStyle = Settings.traceColor();
        ctx.fillText( String( row.n ) , p[ 0 ] + 3 * unit , p[ 1 ] - 3 * unit );
      }
    } );
    const blob = await new Promise( ( resolve ) => canvas.toBlob( resolve , "image/png" ) );
    return new Uint8Array( await blob.arrayBuffer() );
  },
};
