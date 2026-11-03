// Exports of the accepted AIS the table shows (this batch, or all): the CSV on
// its own, or one ZIP holding the CSV and, per image, a full-resolution PNG
// with every accepted trace drawn and numbered as the Saved layer draws it.
// Rendering happens here from the server's preview of each image, so it
// works at any point in a batch. The Batches screen's reports (one batch or
// all) come from here too: an Excel workbook (xlsx.js), or a ZIP with it and
// what the Export dialog asks for -- the traced PNGs (as before), the
// original files, the processed images, a .czi's channels as 16-bit TIFFs,
// and (admins, blinded batches) an Original-names folder of links to them
// with the batch's __Translation.txt.
const AisExport = {
  cols: [ "batch_name" , "batch_id" , "image" , "n" , "file" , "source" , "length_um" , "start_um" , "end_um" , "mid_um" , "max_um" , "arc_um" ,
    "threshold_initial" , "threshold" , "click_x" , "click_y" , "click2_x" , "click2_y" , "profile_points" ,
    "smooth" , "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ,
    "width_um" , "brightness" , "soma_um" , "soma_px" , "soma_ais_x" , "soma_ais_y" , "soma_x" , "soma_y" , "origin" , "accepted_at" , "edited_at" , "notes" ],
  // The method settings each row was measured with; rows from before these
  // were saved leave them blank.
  settingCols: [ "smooth" , "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ],

  linkKey: "ais-export-links",
  bigBytes: 2 * 1024 * 1024 * 1024,

  init() {
    Dom.get( "ais-export-csv" ).addEventListener( "click" , () => this.exportCsv() );
    Dom.get( "ais-export-zip" ).addEventListener( "click" , () => this.exportZip() );
    this.optionsModal = bootstrap.Modal.getOrCreateInstance( Dom.get( "export-options-modal" ) );
    Dom.get( "export-options-names" ).addEventListener( "change" , () => this.renderOptions() );
    Dom.get( "export-options-go" ).addEventListener( "click" , () => this.goOptions() );
  },

  // --- the Export dialog (a ZIP from the Batches screen) -------------------------

  // list: the batches (Batches rows), label for the dialog; onGo( options )
  // runs the export with { traces, originals, processed, channels, names:
  // null | "symlink" | "shortcut" | "copy" }.
  openOptions( list , label , onGo ) {
    this.optionsGo = onGo;
    Dom.text( Dom.get( "export-options-batch" ) , label );
    [ "traces" , "originals" , "processed" , "channels" ].forEach( ( key ) => {
      Dom.get( "export-options-" + key ).checked = key === "traces";
    } );
    const blinded = Batches.admin() && list.some( ( b ) => b.randomized );
    Dom.show( Dom.get( "export-options-blind" ) , blinded );
    Dom.get( "export-options-names" ).checked = false;
    let links = null;
    try {
      links = window.localStorage.getItem( this.linkKey );
    } catch ( error ) { /* storage blocked: the default */ }
    Dom.get( "export-options-links" ).value = links || this.defaultLinks();
    this.renderOptions();
    this.optionsModal.show();
  },

  // Shortcuts for a Windows computer, symbolic links for the others.
  defaultLinks() {
    const platform = ( navigator.userAgentData && navigator.userAgentData.platform ) || navigator.platform || "";
    return /win/i.test( platform ) ? "shortcut" : "symlink";
  },

  renderOptions() {
    Dom.get( "export-options-links" ).disabled = !Dom.get( "export-options-names" ).checked;
  },

  goOptions() {
    const checked = ( key ) => Dom.get( "export-options-" + key ).checked;
    const blinded = !Dom.get( "export-options-blind" ).hidden;
    const links = Dom.get( "export-options-links" ).value;
    try {
      window.localStorage.setItem( this.linkKey , links );
    } catch ( error ) { /* storage blocked */ }
    const options = { traces: checked( "traces" ) , originals: checked( "originals" ) , processed: checked( "processed" ) ,
      channels: checked( "channels" ) , names: blinded && checked( "names" ) ? links : null };
    this.optionsModal.hide();
    if ( this.optionsGo ) this.optionsGo( options );
  },

  csv( rows ) {
    const quote = ( v ) => {
      const s = v == null ? "" : String( v );
      return /[",\n]/.test( s ) ? '"' + s.replace( /"/g , '""' ) + '"' : s;
    };
    return [ this.cols.join( "," ) ].concat( rows.map( ( row ) => this.cols.map( ( c ) => quote( row[ c ] ) ).join( "," ) ) ).join( "\n" ) + "\n";
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

  exportZip() {
    const rows = Ais.shownRows();
    if ( !rows.length ) return;
    return this.zip( rows , this.baseName() , ( done , total ) => Ais.status( total
      ? I18n.get( "ais.exporting" ).replace( "{done}" , done ).replace( "{total}" , total ) : "" ) );
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
    const summary = items.map( ( { batch: b , rows } ) => {
      const s = this.stats( rows.map( ( r ) => r.length_um ) );
      return [ b.name , b.id , b.created_by_name || "" , date( b.created_at ) , b.archived_at ? date( b.archived_at ) : "" ,
        b.images , b.completed , b.duplicates || 0 , rows.length , s.mean , s.median , s.sd , s.min , s.max ,
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
    items.forEach( ( { rows } ) => rows.forEach( ( row ) => ais.push( this.cols.map( ( c ) => row[ c ] ) ) ) );
    return [
      { name: I18n.get( "report.sheet_summary" ) , rows: summary , cols: this.header( [ "batch" , "batch_id" , "opened_by" , "created" , "archived" ,
        "images" , "completed" , "duplicates" , "ais" , "mean_um" , "median_um" , "sd_um" , "min_um" , "max_um" , "ais_per_image" ] ) },
      { name: I18n.get( "report.sheet_images" ) , rows: images , cols: this.header( [ "batch" , "image" , "state" , "ais" , "mean_um" , "median_um" , "assignee" ] ) },
      { name: I18n.get( "report.sheet_assignees" ) , rows: assignees , cols: this.header( [ "batch" , "person" , "images" , "completed" , "percent" , "ais" , "last_activity" ] ) },
      { name: I18n.get( "report.sheet_ais" ) , rows: ais , cols: this.cols },
    ];
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
  // openOptions; none given: the traces only).
  async exportReport( items , label , kind , progress , options ) {
    const base = "ais_" + this.safe( label ) + "_" + new Date().toISOString().slice( 0 , 10 );
    const sheets = this.sheets( items );
    const workbook = Xlsx.build( sheets );
    if ( kind === "xlsx" ) {
      this.download( workbook , base + ".xlsx" );
      return;
    }
    const rows = items.flatMap( ( item ) => item.rows );
    const opts = options || { traces: true };
    const files = await this.imageFiles( items , opts , progress );
    if ( files === null ) return;
    await this.zip( rows , base , progress , [
      { name: "report.xlsx" , data: new Uint8Array( await workbook.arrayBuffer() ) },
      { name: "summary.csv" , data: this.sheetCsv( sheets[ 0 ] ) },
    ].concat( files ) , opts.traces !== false );
  },

  // --- the image files of a ZIP ------------------------------------------------------

  async bytes( url ) {
    const response = await fetch( url , { credentials: "same-origin" } );
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
  // channels: each of a .czi's channels.
  async planImage( image , opts ) {
    const out = [];
    const f = image.files;
    const file = ( folder , x ) => out.push( { folder: folder , name: x.name , url: "/api/ais/files/" + x.sha + "/file" , size: x.size || 0 } );
    if ( opts.originals ) {
      if ( f.czi ) file( "originals" , f.czi );
      else if ( f.raw ) file( "originals" , f.raw );
      else if ( f.processed ) file( "originals" , f.processed );
    }
    if ( opts.processed ) {
      if ( f.czi ) {
        out.push( { folder: "processed" , name: image.cell + Ais.processedSuffix , url: "/api/ais/files/" + f.czi.sha + "/processed.tif" ,
          size: f.czi.size || 0 } );
      } else if ( f.processed && f.raw ) {
        file( "processed" , f.processed );
      }
    }
    if ( opts.channels && f.czi ) {
      const channels = ( await Api.request( "/api/ais/files/" + f.czi.sha + "/channels" ) ).channels;
      channels.forEach( ( c , i ) => out.push( { folder: "channels" , name: image.cell + "_c" + ( i + 1 ) + "_" + this.safe( c.name ) + ".tif" ,
        url: "/api/ais/files/" + f.czi.sha + "/channel/" + c.index + ".tif" , size: 0 } ) );
    }
    return out;
  },

  // The ZIP entries of every included image's files, in a folder per batch
  // when there are several, each kind of file in its own folder; and with
  // names, an "original names" folder pointing at them and __Translation.txt.
  // null when it would be too big and the person says not to go on.
  async imageFiles( items , opts , progress ) {
    if ( !opts.originals && !opts.processed && !opts.channels ) return [];
    const multi = items.length > 1;
    const plan = [];
    const extra = [];
    for ( const item of items ) {
      const prefix = multi ? this.safe( item.batch.name ) + "/" : "";
      const batch = await Api.request( "/api/ais/batches/" + item.batch.id );
      const excluded = new Set( batch.excluded || [] );
      for ( const image of batch.images ) {
        if ( excluded.has( image.key ) ) continue;
        const dir = image.dir ? image.dir + "/" : "";
        ( await this.planImage( image , opts ) ).forEach( ( p ) => plan.push( Object.assign( p , { prefix: prefix , dir: dir , image: image } ) ) );
      }
      if ( opts.names && batch.images.some( ( image ) => image.original_key ) ) {
        extra.push( { name: prefix + "__Translation.txt" , data: await this.bytes( "/api/ais/batches/" + batch.id + "/translation.txt" ) } );
      }
    }
    const total = plan.reduce( ( sum , p ) => sum + p.size , 0 ) * ( opts.names === "copy" ? 2 : 1 );
    if ( total > this.bigBytes && !window.confirm( I18n.get( "batches.export_big" ).replace( "{size}" , AisImages.size( total ) ) ) ) return null;
    const files = new Array( plan.length );
    let done = 0;
    progress( 0 , plan.length );
    await Ais.pool( plan , Ais.concurrency , async ( p , i ) => {
      files[ i ] = { name: p.prefix + p.folder + "/" + p.dir + p.name , data: await this.bytes( p.url ) };
      done += 1;
      progress( done , plan.length );
    } );
    const out = files.slice();
    if ( opts.names ) {
      plan.forEach( ( p , i ) => {
        const image = p.image;
        if ( !image.original_key || !p.name.startsWith( image.cell ) ) return;
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
    return out.concat( extra );
  },

  // The traced image's id on the server, stored with the row. If this
  // browser picked that image and has not uploaded it yet, it does now.
  async shaFor( row ) {
    const entry = Ais.batch && row.batch_id === Ais.batch.id ? Ais.images.find( ( e ) => e.key === row.image ) : null;
    if ( entry ) await Ais.upload( entry );
    return row.sha || ( entry ? Ais.sha( entry ) : null );
  },

  loadImage( url ) {
    return new Promise( ( resolve , reject ) => {
      const img = new Image();
      img.onload = () => resolve( img );
      img.onerror = () => reject( new Error( "image not available" ) );
      img.src = url;
    } );
  },

  async render( sha , rows ) {
    const img = await this.loadImage( "/api/ais/files/" + sha + "/view.png" );
    const canvas = document.createElement( "canvas" );
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext( "2d" );
    ctx.drawImage( img , 0 , 0 );
    const unit = Math.max( 1 , Math.max( canvas.width , canvas.height ) / 700 );
    ctx.font = "bold " + Math.round( 12 * unit ) + "px sans-serif";
    rows.forEach( ( row ) => {
      Ais.polyline( row.pixels , "rgba(60, 220, 120, 0.95)" , Settings.lineWidth() * unit , ctx );
      const p = row.pixels && row.pixels[ 0 ];
      if ( p ) {
        ctx.lineWidth = 3 * unit;
        ctx.strokeStyle = "rgba(0, 0, 0, 0.8)";
        ctx.strokeText( String( row.n ) , p[ 0 ] + 3 * unit , p[ 1 ] - 3 * unit );
        ctx.fillStyle = "rgba(60, 220, 120, 1)";
        ctx.fillText( String( row.n ) , p[ 0 ] + 3 * unit , p[ 1 ] - 3 * unit );
      }
    } );
    const blob = await new Promise( ( resolve ) => canvas.toBlob( resolve , "image/png" ) );
    return new Uint8Array( await blob.arrayBuffer() );
  },
};
