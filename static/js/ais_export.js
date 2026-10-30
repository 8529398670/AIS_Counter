// Exports of the accepted AIS the table shows (this batch, or all): the CSV on
// its own, or one ZIP holding the CSV and, per image, a full-resolution PNG
// with every accepted trace drawn and numbered as the Saved layer draws it.
// Rendering happens here from the server's preview of each image, so it
// works at any point in a batch.
const AisExport = {
  cols: [ "batch_name" , "batch_id" , "image" , "n" , "file" , "source" , "length_um" , "start_um" , "end_um" , "mid_um" , "max_um" , "arc_um" ,
    "threshold_initial" , "threshold" , "click_x" , "click_y" , "click2_x" , "click2_y" , "profile_points" , "accepted_at" , "notes" ],

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

  // "ais_<batch>_<yyyy-mm-dd>" for the current batch, "ais_all_<date>" otherwise.
  baseName() {
    const all = Dom.get( "ais-table-scope" ).value === "all" || !Ais.batch;
    const label = all ? "all" : Ais.batch.name;
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

  async exportZip() {
    const rows = Ais.shownRows();
    if ( !rows.length ) return;
    // One PNG per image: rows grouped by batch and image.
    const groups = new Map();
    rows.forEach( ( row ) => {
      const key = row.batch_id + "\n" + row.image;
      if ( !groups.has( key ) ) groups.set( key , [] );
      groups.get( key ).push( row );
    } );
    const multiBatch = new Set( rows.map( ( row ) => row.batch_id ) ).size > 1;
    const files = [ { name: "results.csv" , data: this.csv( rows ) } ];
    const missing = [];
    let done = 0;
    for ( const group of groups.values() ) {
      done += 1;
      Ais.status( I18n.get( "ais.exporting" ).replace( "{done}" , done ).replace( "{total}" , groups.size ) );
      const first = group[ 0 ];
      try {
        const sha = await this.shaFor( first );
        if ( !sha ) throw new Error( "image not available" );
        const png = await this.render( sha , group );
        const folder = multiBatch ? this.safe( first.batch_name || "batch" ) + "/" : "";
        files.push( { name: folder + this.safe( first.image.replace( /\//g , "__" ) ) + "_traces.png" , data: png } );
      } catch ( error ) {
        missing.push( ( first.batch_name ? first.batch_name + " / " : "" ) + first.image + ": " + error.message );
      }
    }
    if ( missing.length ) files.push( { name: "missing.txt" , data: missing.join( "\n" ) + "\n" } );
    Ais.status( "" );
    this.download( Zip.build( files ) , this.baseName() + ".zip" );
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
