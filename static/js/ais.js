// The AIS tracing screen: open a folder of TIFF pairs, click near an AIS, see
// the original ais_auto.m's trace and length, accept or reject it.
//
// The analysis is all server-side (app/analysis/). This file uploads each
// image the first time it is shown, draws it with the overlays the original
// plotted (red skeleton dots, the blue rounded trace, the yellow spline), and
// keeps the accepted results in this browser until they are exported as CSV.
//
// Coordinates sent to and received from the server are MATLAB axes
// coordinates: x = column, y = row, pixel centres at 1..n. On the canvas a
// pixel (x, y) covers [x-1, x) x [y-1, y) in image units.
const Ais = {
  processedSuffix: ".tif - Processed method 2.5.tif",
  storageKey: "ais-results",
  images: [],
  index: -1,
  bitmap: null,          // the current image, brightness applied, as a canvas
  source: null,          // its decoded <img>
  view: { scale: 1 , ox: 0 , oy: 0 },
  result: null,          // the last trace answer from the server
  firstClick: null,      // two-click mode: waiting for the second click
  results: [],
  busy: false,

  init() {
    this.canvas = Dom.get( "ais-canvas" );
    this.ctx = this.canvas.getContext( "2d" );
    this.results = this.loadResults();

    Dom.get( "ais-folder" ).addEventListener( "change" , ( e ) => this.openFiles( e.target.files ) );
    Dom.get( "ais-files" ).addEventListener( "change" , ( e ) => this.openFiles( e.target.files ) );
    Dom.get( "ais-image" ).addEventListener( "change" , ( e ) => this.show( Number( e.target.value ) ) );
    Dom.get( "ais-prev" ).addEventListener( "click" , () => this.step( -1 ) );
    Dom.get( "ais-next" ).addEventListener( "click" , () => this.step( 1 ) );
    Dom.get( "ais-gamma" ).addEventListener( "input" , () => { this.buildBitmap(); this.draw(); } );
    Dom.all( "[data-layer]" ).forEach( ( box ) => box.addEventListener( "change" , () => this.draw() ) );
    Dom.get( "ais-accept" ).addEventListener( "click" , () => this.accept() );
    Dom.get( "ais-reject" ).addEventListener( "click" , () => this.reject() );
    Dom.get( "ais-export" ).addEventListener( "click" , () => this.exportCsv() );
    Dom.get( "ais-clear" ).addEventListener( "click" , () => this.clearResults() );
    Dom.get( "ais-two-clicks" ).addEventListener( "change" , () => { this.firstClick = null; this.status( "" ); } );

    this.bindCanvas();
    document.addEventListener( "keydown" , ( e ) => this.onKey( e ) );
    // The stage has no size while its view is hidden, so size the canvas
    // whenever the stage itself changes size, including when it first shows.
    new ResizeObserver( () => this.resize() ).observe( Dom.get( "ais-stage" ) );
    this.renderPicker();
    this.renderTable();
    this.resize();
  },

  // --- opening images ------------------------------------------------------

  // Group the chosen files by cell: "<cell>.tif" is the raw image the profile
  // is sampled from, "<cell>.tif - Processed method 2.5.tif" the one traced.
  openFiles( fileList ) {
    const byCell = new Map();
    Array.from( fileList ).forEach( ( file ) => {
      const name = file.name;
      let cell = null;
      let role = null;
      if ( name.endsWith( this.processedSuffix ) ) {
        cell = name.slice( 0 , -this.processedSuffix.length ).replace( /\.tif$/i , "" );
        role = "processed";
      } else if ( /\.tiff?$/i.test( name ) && !name.startsWith( "." ) ) {
        cell = name.replace( /\.tiff?$/i , "" );
        role = "raw";
      }
      if ( !cell ) return;
      const entry = byCell.get( cell ) || { cell: cell , files: {} , sha: {} };
      entry.files[ role ] = file;
      byCell.set( cell , entry );
    } );
    this.images = Array.from( byCell.values() )
      .filter( ( entry ) => entry.files.processed )
      .sort( ( a , b ) => a.cell.localeCompare( b.cell ) );
    this.renderPicker();
    if ( this.images.length ) this.show( 0 );
  },

  renderPicker() {
    const select = Dom.get( "ais-image" );
    Dom.clear( select );
    if ( !this.images.length ) {
      select.appendChild( Dom.el( "option" , { text: I18n.get( "ais.no_images" ) } ) );
      select.disabled = true;
      return;
    }
    select.disabled = false;
    this.images.forEach( ( entry , i ) => {
      const count = this.results.filter( ( r ) => r.image === entry.cell ).length;
      const label = ( i + 1 ) + ". " + entry.cell + ( entry.files.raw ? "" : " *" ) + ( count ? "  (" + count + ")" : "" );
      select.appendChild( Dom.el( "option" , { text: label , attrs: { value: String( i ) } } ) );
    } );
    select.value = String( Math.max( this.index , 0 ) );
  },

  step( delta ) {
    if ( !this.images.length ) return;
    const next = Math.min( this.images.length - 1 , Math.max( 0 , this.index + delta ) );
    if ( next !== this.index ) this.show( next );
  },

  async show( index ) {
    this.index = index;
    this.result = null;
    this.firstClick = null;
    this.renderResult();
    Dom.get( "ais-image" ).value = String( index );
    const entry = this.images[ index ];
    try {
      await this.upload( entry );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    if ( this.index !== index ) return;   // moved on while uploading
    const img = new Image();
    img.onload = () => {
      if ( this.index !== index ) return;
      this.source = img;
      this.buildBitmap();
      this.fit();
      Dom.show( Dom.get( "ais-empty" ) , false );
      this.status( entry.files.raw ? "" : I18n.get( "ais.no_raw" ) );
      this.draw();
    };
    img.src = "/api/ais/files/" + entry.sha.processed + "/view.png";
    // Upload the next pair in the background so stepping through is quick.
    const next = this.images[ index + 1 ];
    if ( next ) this.upload( next ).catch( () => {} );
  },

  async upload( entry ) {
    for ( const role of [ "processed" , "raw" ] ) {
      const file = entry.files[ role ];
      if ( !file || entry.sha[ role ] ) continue;
      if ( !entry.pending ) entry.pending = {};
      if ( !entry.pending[ role ] ) {
        entry.pending[ role ] = ( async () => {
          if ( this.images[ this.index ] === entry ) this.status( I18n.get( "ais.uploading" ).replace( "{name}" , file.name ) );
          const data = await this.base64( file );
          const info = await Api.post( "/api/ais/files" , { data: data } );
          entry.sha[ role ] = info.sha256;
        } )();
      }
      try {
        await entry.pending[ role ];
      } finally {
        delete entry.pending[ role ];
      }
    }
  },

  base64( file ) {
    return new Promise( function ( resolve , reject ) {
      const reader = new FileReader();
      reader.onload = function () { resolve( String( reader.result ).split( "," )[ 1 ] || "" ); };
      reader.onerror = function () { reject( new Error( "could not read " + file.name ) ); };
      reader.readAsDataURL( file );
    } );
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
    if ( this.bitmap && !this.fitted ) this.fit();
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

  toImage( event ) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: ( event.clientX - rect.left - this.view.ox ) / this.view.scale,
      y: ( event.clientY - rect.top - this.view.oy ) / this.view.scale,
    };
  },

  bindCanvas() {
    let down = null;
    this.canvas.addEventListener( "pointerdown" , ( e ) => {
      down = { x: e.clientX , y: e.clientY , ox: this.view.ox , oy: this.view.oy , moved: false };
      this.canvas.setPointerCapture( e.pointerId );
    } );
    this.canvas.addEventListener( "pointermove" , ( e ) => {
      if ( !down ) return;
      const dx = e.clientX - down.x;
      const dy = e.clientY - down.y;
      if ( Math.abs( dx ) + Math.abs( dy ) > 4 ) down.moved = true;
      if ( down.moved ) {
        this.view.ox = down.ox + dx;
        this.view.oy = down.oy + dy;
        this.draw();
      }
    } );
    this.canvas.addEventListener( "pointerup" , ( e ) => {
      const wasClick = down && !down.moved;
      down = null;
      if ( wasClick && e.button === 0 ) this.onClick( this.toImage( e ) );
    } );
    this.canvas.addEventListener( "wheel" , ( e ) => {
      if ( !this.bitmap ) return;
      e.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const factor = Math.exp( -e.deltaY * 0.0015 );
      const scale = Math.min( 40 , Math.max( 0.05 , this.view.scale * factor ) );
      this.view.ox = cx - ( cx - this.view.ox ) * scale / this.view.scale;
      this.view.oy = cy - ( cy - this.view.oy ) * scale / this.view.scale;
      this.view.scale = scale;
      this.draw();
    } , { passive: false } );
    this.canvas.addEventListener( "dblclick" , () => { this.fit(); this.draw(); } );
  },

  onKey( event ) {
    if ( !Nav || Nav.current() !== "ais" ) return;
    const tag = ( event.target.tagName || "" ).toLowerCase();
    if ( tag === "input" || tag === "select" || tag === "textarea" ) return;
    if ( event.key === "Enter" ) { event.preventDefault(); this.accept(); }
    else if ( event.key === "n" || event.key === "N" ) this.reject();
    else if ( event.key === "ArrowRight" ) this.step( 1 );
    else if ( event.key === "ArrowLeft" ) this.step( -1 );
  },

  // --- tracing -------------------------------------------------------------

  async onClick( point ) {
    const entry = this.images[ this.index ];
    if ( !entry || !entry.sha.processed || this.busy ) return;
    if ( point.x < 0 || point.y < 0 || point.x >= this.bitmap.width || point.y >= this.bitmap.height ) return;
    // Canvas pixel j spans [j, j+1); in MATLAB axes its centre is j+1.
    const click = [ point.x + 0.5 , point.y + 0.5 ];
    const body = {
      processed: entry.sha.processed,
      raw: entry.sha.raw || null,
      threshold: Number( Dom.get( "ais-threshold" ).value ),
      click: click,
    };
    if ( this.firstClick ) {
      body.click = this.firstClick;
      body.click2 = click;
    }
    this.busy = true;
    this.status( I18n.get( "ais.tracing" ) );
    try {
      const result = await Api.post( "/api/ais/trace" , body );
      const twoClicks = Dom.get( "ais-two-clicks" ).checked;
      if ( twoClicks && !this.firstClick && result.rethresholded ) {
        // The original asks for a second click after re-thresholding.
        this.firstClick = click;
        this.result = result;
        this.status( I18n.get( "ais.second_click" ).replace( "{threshold}" , this.fmt( result.threshold ) ) );
        this.renderResult( true );
        this.draw();
        return;
      }
      this.firstClick = null;
      this.result = Object.assign( result , { image: entry.cell , click: body.click , click2: body.click2 || null } );
      this.status( entry.files.raw ? "" : I18n.get( "ais.no_raw" ) );
      this.renderResult();
      this.draw();
    } catch ( error ) {
      this.status( "" );
      App.showError( error.message );
    } finally {
      this.busy = false;
    }
  },

  status( text ) {
    const box = Dom.get( "ais-status" );
    Dom.text( box , text );
    Dom.show( box , Boolean( text ) );
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

    const notes = Dom.get( "ais-notes" );
    Dom.clear( notes );
    ( r.notes || [] ).forEach( ( note ) => notes.appendChild( Dom.el( "li" , { text: note } ) ) );
    this.renderProfile( r.profile );
    Dom.get( "ais-accept" ).disabled = !( r.ok && !waitingForSecond );
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

  accept() {
    const r = this.result;
    if ( !r || !r.ok ) return;
    const m = r.measures;
    const sameImage = this.results.filter( ( row ) => row.image === r.image );
    this.results.push( {
      image: r.image,
      n: sameImage.length ? Math.max.apply( null , sameImage.map( ( row ) => row.n ) ) + 1 : 1,
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
      notes: ( r.notes || [] ).join( "; " ),
      pixels: r.pixels,
    } );
    this.saveResults();
    this.result = null;
    this.renderResult();
    this.renderTable();
    this.renderPicker();
    this.draw();
  },

  reject() {
    this.result = null;
    this.firstClick = null;
    this.status( "" );
    this.renderResult();
    this.draw();
  },

  // --- results -------------------------------------------------------------

  loadResults() {
    try {
      const parsed = JSON.parse( window.localStorage.getItem( this.storageKey ) || "[]" );
      return Array.isArray( parsed ) ? parsed : [];
    } catch ( error ) {
      return [];
    }
  },

  saveResults() {
    try {
      window.localStorage.setItem( this.storageKey , JSON.stringify( this.results ) );
    } catch ( error ) { /* storage full or blocked: export still works this session */ }
  },

  renderTable() {
    const body = Dom.get( "ais-table" ).querySelector( "tbody" );
    Dom.clear( body );
    this.results.forEach( ( row , i ) => {
      const del = Dom.el( "button" , {
        class: "btn btn-sm btn-link text-danger p-0",
        attrs: { title: I18n.get( "ais.reject" ) },
        children: [ Dom.el( "i" , { class: "bi bi-trash" } ) ],
        on: { click: () => { this.results.splice( i , 1 ); this.saveResults(); this.renderTable(); this.renderPicker(); this.draw(); } },
      } );
      body.appendChild( Dom.el( "tr" , { children: [
        Dom.el( "td" , { text: row.image , class: "text-truncate ais-cell-name" } ),
        Dom.el( "td" , { text: row.n } ),
        Dom.el( "td" , { text: row.length_str , class: "fw-semibold" } ),
        Dom.el( "td" , { text: this.fmt( row.start_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.end_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.max_um ) } ),
        Dom.el( "td" , { text: this.fmt( row.threshold ) } ),
        Dom.el( "td" , { text: "(" + row.click_x + ", " + row.click_y + ")" } ),
        Dom.el( "td" , { children: [ del ] } ),
      ] } ) );
    } );
  },

  exportCsv() {
    const cols = [ "image" , "n" , "length_um" , "start_um" , "end_um" , "mid_um" , "max_um" , "arc_um" ,
      "threshold_initial" , "threshold" , "click_x" , "click_y" , "click2_x" , "click2_y" , "profile_points" , "notes" ];
    const quote = ( v ) => {
      const s = v == null ? "" : String( v );
      return /[",\n]/.test( s ) ? '"' + s.replace( /"/g , '""' ) + '"' : s;
    };
    const lines = [ cols.join( "," ) ].concat( this.results.map( ( row ) => cols.map( ( c ) => quote( row[ c ] ) ).join( "," ) ) );
    const blob = new Blob( [ lines.join( "\n" ) + "\n" ] , { type: "text/csv" } );
    const link = Dom.el( "a" , { attrs: { href: URL.createObjectURL( blob ) , download: "ais_results.csv" } } );
    document.body.appendChild( link );
    link.click();
    link.remove();
  },

  clearResults() {
    const question = I18n.get( "ais.clear_confirm" );
    if ( !this.results.length || ( question && !window.confirm( question ) ) ) return;
    this.results = [];
    this.saveResults();
    this.renderTable();
    this.renderPicker();
    this.draw();
  },

  // --- drawing -------------------------------------------------------------

  layer( name ) {
    const box = document.querySelector( '[data-layer="' + name + '"]' );
    return !box || box.checked;
  },

  draw() {
    const ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform( 1 , 0 , 0 , 1 , 0 , 0 );
    ctx.clearRect( 0 , 0 , this.canvas.width , this.canvas.height );
    if ( !this.bitmap ) return;
    const s = this.view.scale;
    ctx.setTransform( dpr * s , 0 , 0 , dpr * s , dpr * this.view.ox , dpr * this.view.oy );
    ctx.imageSmoothingEnabled = s < 1;
    ctx.drawImage( this.bitmap , 0 , 0 );
    const lw = 1.5 / s;

    const entry = this.images[ this.index ];
    if ( entry && this.layer( "saved" ) ) {
      this.results.filter( ( row ) => row.image === entry.cell ).forEach( ( row ) => {
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
      if ( r.start ) this.cross( r.start , "rgba(255, 255, 255, 1)" , 4 / s , lw );
      ( r.clicks || [] ).forEach( ( c ) => this.cross( c , "rgba(255, 150, 0, 1)" , 6 / s , lw ) );
    }
    if ( this.firstClick ) this.cross( this.firstClick , "rgba(255, 150, 0, 1)" , 6 / s , lw );
  },

  // Pixels (x, y), 1-based: each fills its own square.
  dots( points , colour ) {
    const ctx = this.ctx;
    ctx.fillStyle = colour;
    points.forEach( ( p ) => ctx.fillRect( p[ 0 ] - 1 , p[ 1 ] - 1 , 1 , 1 ) );
  },

  // Points in MATLAB axes coordinates: centre of pixel x is x - 0.5 here.
  polyline( points , colour , width ) {
    if ( !points || points.length < 2 ) return;
    const ctx = this.ctx;
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
