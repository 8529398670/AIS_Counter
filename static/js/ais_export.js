// Exports of the accepted AIS the table shows (this batch, or all): the CSV on
// its own, or one ZIP holding the CSV and, per image, a full-resolution PNG
// with every accepted trace drawn and numbered as the Saved layer draws it.
// Rendering happens here from the server's preview of each image, so it
// works at any point in a batch. The Batches screen's reports (one batch or
// all) come from here too: an Excel workbook (xlsx.js), or a ZIP with it.
const AisExport = {
  cols: [ "batch_name" , "batch_id" , "image" , "n" , "file" , "source" , "length_um" , "start_um" , "end_um" , "mid_um" , "max_um" , "arc_um" ,
    "threshold_initial" , "threshold" , "click_x" , "click_y" , "click2_x" , "click2_y" , "profile_points" ,
    "smooth" , "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ,
    "width_um" , "brightness" , "origin" , "accepted_at" , "edited_at" , "notes" ],
  // The method settings each row was measured with; rows from before these
  // were saved leave them blank.
  settingCols: [ "smooth" , "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ],

  init() {
    Dom.get( "ais-export-csv" ).addEventListener( "click" , () => this.exportCsv() );
    Dom.get( "ais-export-zip" ).addEventListener( "click" , () => this.exportZip() );
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

  // The ZIP: results.csv, extra (more files, e.g. a batch report) and one PNG
  // per image, rows grouped by batch and image. progress( done , total ) per
  // image, then ( 0 , 0 ) when done.
  async zip( rows , base , progress , extra ) {
    const groups = new Map();
    rows.forEach( ( row ) => {
      const key = row.batch_id + "\n" + row.image;
      if ( !groups.has( key ) ) groups.set( key , [] );
      groups.get( key ).push( row );
    } );
    const multiBatch = new Set( rows.map( ( row ) => row.batch_id ) ).size > 1;
    const files = [ { name: "results.csv" , data: this.csv( rows ) } ].concat( extra || [] );
    // A few images at a time, each put back in its place once drawn.
    const list = Array.from( groups.values() );
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
  // results.csv and the traced PNGs.
  async exportReport( items , label , kind , progress ) {
    const base = "ais_" + this.safe( label ) + "_" + new Date().toISOString().slice( 0 , 10 );
    const sheets = this.sheets( items );
    const workbook = Xlsx.build( sheets );
    if ( kind === "xlsx" ) {
      this.download( workbook , base + ".xlsx" );
      return;
    }
    const rows = items.flatMap( ( item ) => item.rows );
    await this.zip( rows , base , progress , [
      { name: "report.xlsx" , data: new Uint8Array( await workbook.arrayBuffer() ) },
      { name: "summary.csv" , data: this.sheetCsv( sheets[ 0 ] ) },
    ] );
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
