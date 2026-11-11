// Channel roles: which colour channel is the AIS, which the soma/dendrite
// stain, and what the others are called (app/analysis/channels.py decides;
// this asks). One dialog serves both adding images (Channels.ask) and changing
// a batch's roles later (Channels.edit).
//
// A layout is { kind: "czi" | "tiff" , names: [ ... ] }: a .czi's channel
// names from its metadata, a TIFF's planes as Red/Green/Blue or Channel N.
// Files picked in this browser are read here (readLayout, while they are
// hashed); a folder on the server is read there (/api/ais/local/channels).
const Channels = {
  aisChannel: "Alexa Fluor 488",
  somaStains: [ "AMCA" , "DAPI" , "Hoechst" ],
  rgbNames: [ "Red" , "Green" , "Blue" ],
  fallbackColors: [ "#00ff33" , "#ff0000" , "#0040ff" , "#ff00ff" , "#ffff00" , "#00ffff" ],
  tiffColors: [ "#ff0000" , "#00ff00" , "#0000ff" , "#ffffff" ],
  answer: null,
  blocks: [],

  init() {
    const element = Dom.get( "channels-modal" );
    // Open path can ask from the Process screen, with Batches hidden.
    document.body.appendChild( element );
    this.modal = bootstrap.Modal.getOrCreateInstance( element );
    Dom.get( "channels-form" ).addEventListener( "submit" , ( e ) => { e.preventDefault(); this.submit(); } );
    element.addEventListener( "hidden.bs.modal" , () => {
      if ( this.answer ) this.answer( null );
      this.answer = null;
    } );
  },

  // --- reading layouts ---------------------------------------------------------

  // { layout , colors } of a picked file's bytes, or null when they can't be
  // read; colors only for a .czi.
  readLayout( buffer ) {
    try {
      const view = new DataView( buffer );
      const out = this.isCzi( view ) ? this.readCzi( view ) : this.readTiff( view );
      if ( !out || !out.layout.names.length || out.layout.names.length > 16 ) return null;
      out.layout.names = out.layout.names.map( ( n ) => n.trim() );
      return out;
    } catch ( error ) {
      return null;   // a truncated or odd file: the server reads it later
    }
  },

  isCzi( view ) {
    return view.byteLength >= 10 && this.ascii( view , 0 , 10 ) === "ZISRAWFILE";
  },

  ascii( view , at , n ) {
    let out = "";
    for ( let i = 0; i < n; i += 1 ) {
      const c = view.getUint8( at + i );
      if ( !c ) break;
      out += String.fromCharCode( c );
    }
    return out;
  },

  // As app/analysis/czi.py read_channels: the channels are the C starts of
  // the directory's entries, named from the metadata, each with ZEN's colour.
  readCzi( view ) {
    const directory = Number( view.getBigInt64( 32 + 52 , true ) );
    const metadata = Number( view.getBigInt64( 32 + 60 , true ) );
    if ( this.ascii( view , directory , 16 ) !== "ZISRAWDIRECTORY" ) return null;
    let pos = directory + 32;
    const count = view.getInt32( pos , true );
    pos += 128;
    const starts = new Set();
    for ( let e = 0; e < count; e += 1 ) {
      if ( this.ascii( view , pos , 2 ) !== "DV" ) return null;
      const pyramid = view.getUint8( pos + 22 );
      const ndims = view.getInt32( pos + 28 , true );
      let c = 0;
      for ( let d = 0; d < ndims; d += 1 ) {
        const at = pos + 32 + d * 20;
        if ( this.ascii( view , at , 4 ) === "C" ) c = view.getInt32( at + 4 , true );
      }
      if ( pyramid === 0 ) starts.add( c );
      pos += 32 + ndims * 20;
    }
    const n = starts.size;
    let xml = null;
    if ( metadata && this.ascii( view , metadata , 16 ) === "ZISRAWMETADATA" ) {
      const at = metadata + 32;
      const size = view.getInt32( at , true );
      const text = new TextDecoder().decode( new Uint8Array( view.buffer , at + 256 , size ) );
      xml = new DOMParser().parseFromString( text , "text/xml" );
      if ( xml.getElementsByTagName( "parsererror" ).length ) xml = null;
    }
    let names = xml ? Array.from( xml.querySelectorAll( "Information > Image > Dimensions > Channels > Channel" ) )
      .map( ( c ) => c.getAttribute( "Name" ) || c.getAttribute( "Id" ) || "" ) : [];
    if ( names.length !== n || new Set( names ).size !== n || !names.every( Boolean ) ) {
      names = Array.from( { length: n } , ( _ , i ) => "channel " + ( i + 1 ) );
    }
    const found = {};
    if ( xml ) {
      xml.querySelectorAll( "DisplaySetting > Channels > Channel" ).forEach( ( c ) => {
        const color = ( ( c.querySelector( ":scope > Color" ) || {} ).textContent || "" ).trim().replace( /^#+/ , "" );
        if ( color.length === 8 ) found[ c.getAttribute( "Name" ) ] = "#" + color.slice( 2 ).toLowerCase();
      } );
    }
    const colors = names.map( ( name , i ) => found[ name ] || this.fallbackColors[ i % this.fallbackColors.length ] );
    return { layout: { kind: "czi" , names: names } , colors: colors };
  },

  // As app/analysis/images.py tiff_names: the first page's samples.
  readTiff( view ) {
    const found = Tiff.samples( view );
    if ( !found ) return null;
    const count = Math.min( found.samples , 4 );
    return { layout: { kind: "tiff" , names: this.tiffNames( count , found.rgb ) } , colors: null };
  },

  tiffNames( count , rgb ) {
    return Array.from( { length: count } , ( _ , i ) => rgb && i < 3 ? this.rgbNames[ i ] : "Channel " + ( i + 1 ) );
  },

  // --- roles, as app/analysis/channels.py ------------------------------------------

  same( a , b ) {
    return Boolean( a && b ) && a.kind === b.kind && a.names.length === b.names.length && a.names.every( ( n , i ) => n === b.names[ i ] );
  },

  somaIndex( names ) {
    for ( const stain of this.somaStains ) {
      const i = names.findIndex( ( n ) => n.toLowerCase().includes( stain.toLowerCase() ) );
      if ( i >= 0 ) return i;
    }
    return null;
  },

  defaultRoles( layout ) {
    let ais = 0;
    let soma = null;
    if ( layout.kind === "czi" ) {
      soma = this.somaIndex( layout.names );
      ais = layout.names.indexOf( this.aisChannel );
      if ( ais < 0 ) {
        ais = layout.names.findIndex( ( _ , i ) => i !== soma );
        if ( ais < 0 ) ais = 0;
      }
    }
    return layout.names.map( ( name , i ) => i === ais ? { role: "ais" , label: "" }
      : i === soma ? { role: "soma" , label: "" } : { role: "other" , label: name } );
  },

  // Picked files ({ layout , colors , stack }) -> one entry per layout, in the
  // order first met: { layout , colors , count , stacks , roles }.
  summarize( found ) {
    const out = [];
    found.forEach( ( f ) => {
      let here = out.find( ( o ) => this.same( o.layout , f.layout ) );
      if ( !here ) {
        here = { layout: f.layout , colors: f.colors , count: 0 , stacks: 0 };
        out.push( here );
      }
      here.count += 1;
      if ( f.stack ) here.stacks += 1;
    } );
    out.forEach( ( o ) => { o.roles = this.defaultRoles( o.layout ); } );
    return out;
  },

  // Only layouts with a choice to make.
  choosable( layouts ) {
    return layouts.filter( ( o ) => o.layout.names.length > 1 );
  },

  // --- the dialog ----------------------------------------------------------------

  // Adding images: { layouts (summarize's) , stacks: [{ cell , slices }] } ->
  // { channels , stack } or null when the person backs out. Not asked (and
  // { channels: [] , stack: null } answered) when there is nothing to ask.
  ask( layouts , stacks ) {
    const choosable = this.choosable( layouts ).map( ( o ) => Object.assign( {} , o , {
      // Slices of Z-stacks alone: no guess, as their merged export's AIS is
      // as often green as red. The person picks.
      roles: o.stacks && o.stacks === o.count && o.layout.kind === "tiff"
        ? o.layout.names.map( ( name ) => ( { role: "other" , label: name } ) ) : o.roles,
    } ) );
    if ( !choosable.length && !stacks.length ) return Promise.resolve( { channels: [] , stack: null } );
    const found = [];
    if ( choosable.length ) found.push( I18n.get( "channels.found" ) );
    if ( stacks.length ) {
      found.push( I18n.get( "batches.stack_found" ).replace( "{count}" , stacks.length )
        .replace( "{slices}" , stacks.map( ( s ) => s.slices ).join( ", " ) ) );
    }
    return this.open( {
      title: I18n.get( stacks.length && !choosable.length ? "batches.stack_title" : "channels.title" ),
      found: found.join( " " ),
      layouts: choosable,
      stacks: stacks.length > 0,
      submit: I18n.get( "batches.stack_add" ),
      warning: "",
    } );
  },

  // Changing a batch's roles (or one add's): the batch's layouts from the
  // server, saved there. Answers the server's answer, or null.
  async edit( batchId , addId ) {
    const query = addId ? "?add=" + addId : "";
    const out = await Api.request( "/api/ais/batches/" + batchId + "/layouts" + query );
    const layouts = this.choosable( out.layouts );
    if ( !layouts.length ) {
      Dom.toast( I18n.get( out.unread ? "channels.none_yet" : "channels.none" ) );
      return null;
    }
    const results = layouts.reduce( ( n , o ) => n + o.results , 0 );
    const notes = [];
    if ( out.unread ) notes.push( I18n.get( "channels.unread" ).replace( "{n}" , out.unread ) );
    const chosen = await this.open( {
      title: I18n.get( "channels.title" ),
      found: [ I18n.get( "channels.edit_found" ) , ...notes ].join( " " ),
      layouts: layouts,
      stacks: false,
      submit: I18n.get( "channels.save" ),
      warning: results ? I18n.get( "channels.results_warning" ).replace( "{n}" , results ) : "",
    } );
    if ( !chosen ) return null;
    const saved = await Api.post( "/api/ais/batches/" + batchId + "/layouts" ,
      Object.assign( { channels: chosen.channels } , addId ? { add: addId } : {} ) );
    Ais.batchChanged( saved.batch );
    Dom.toast( I18n.get( saved.changed.length === 1 ? "channels.saved_one" : "channels.saved" ).replace( "{n}" , saved.changed.length ) );
    return saved;
  },

  open( options ) {
    Dom.text( Dom.get( "channels-title" ) , options.title );
    Dom.text( Dom.get( "channels-found" ) , options.found );
    Dom.text( Dom.get( "channels-submit" ) , options.submit );
    const warning = Dom.get( "channels-warning" );
    Dom.text( warning , options.warning );
    Dom.show( warning , Boolean( options.warning ) );
    Dom.get( "channels-form" ).reset();
    Dom.show( Dom.get( "channels-stack" ) , options.stacks );
    Dom.all( "#channels-stack input" ).forEach( ( input ) => { input.disabled = !options.stacks; } );
    if ( options.stacks ) Dom.get( "batches-stack-pixel" ).value = Settings.methods[ 0 ].defaults.pixconv;
    this.showError( "" );
    const holder = Dom.get( "channels-layouts" );
    Dom.clear( holder );
    this.blocks = options.layouts.map( ( o , i ) => this.block( o , i ) );
    this.blocks.forEach( ( b ) => holder.appendChild( b.node ) );
    this.stacksAsked = options.stacks;
    return new Promise( ( resolve ) => {
      this.answer = resolve;
      this.modal.show();
    } );
  },

  // One layout's rows: a swatch, the channel's name, its role, and a label
  // for other. Choosing AIS (or soma) for one channel makes the one that had
  // it other, so there is always at most one of each.
  block( o , index ) {
    const roles = o.roles.map( ( r ) => Object.assign( {} , r ) );
    const rows = [];
    const draw = () => rows.forEach( ( row , i ) => {
      row.select.value = roles[ i ].role;
      row.label.value = roles[ i ].label;
      Dom.show( row.label , roles[ i ].role === "other" );
    } );
    const colors = o.colors || ( o.layout.kind === "tiff" && o.layout.names[ 0 ] === "Red" ? this.tiffColors : null );
    const table = Dom.el( "div" , { class: "vstack gap-2" } );
    o.layout.names.forEach( ( name , i ) => {
      const id = "channels-role-" + index + "-" + i;
      const select = Dom.el( "select" , { class: "form-select form-select-sm channels-role" , attrs: { id: id } , children:
        [ "ais" , "soma" , "other" ].map( ( role ) => Dom.el( "option" , { text: I18n.get( "channels.role_" + role ) , attrs: { value: role } } ) ) } );
      const label = Dom.el( "input" , { class: "form-control form-control-sm" , attrs: { type: "text" , maxlength: "60" ,
        "aria-label": I18n.get( "channels.label_for" ).replace( "{name}" , name ) , placeholder: I18n.get( "channels.label" ) } } );
      select.addEventListener( "change" , () => {
        const role = select.value;
        if ( role !== "other" ) {
          roles.forEach( ( r , k ) => { if ( k !== i && r.role === role ) roles[ k ] = { role: "other" , label: o.layout.names[ k ] }; } );
        }
        roles[ i ] = { role: role , label: role === "other" ? ( roles[ i ].label || name ) : "" };
        this.showError( "" );
        draw();
      } );
      label.addEventListener( "input" , () => { roles[ i ].label = label.value; } );
      rows.push( { select: select , label: label } );
      table.appendChild( Dom.el( "div" , { class: "row g-2 align-items-center" , children: [
        Dom.el( "div" , { class: "col-5 col-sm-4 d-flex align-items-center gap-2 text-truncate" , children: [
          this.swatch( colors ? colors[ i ] : "#888888" ),
          Dom.el( "label" , { class: "text-truncate small" , text: name , attrs: { for: id , title: name } } ),
        ] } ),
        Dom.el( "div" , { class: "col-7 col-sm-4" , children: [ select ] } ),
        Dom.el( "div" , { class: "col-12 col-sm-4" , children: [ label ] } ),
      ] } ) );
    } );
    draw();
    const heading = I18n.get( o.count === 1 ? "channels.files_one" : "channels.files" ).replace( "{n}" , o.count )
      + " · " + o.layout.names.join( " · " );
    const node = Dom.el( "fieldset" , { class: "border rounded p-2 mb-3" , children: [
      Dom.el( "legend" , { class: "float-none w-auto px-1 mb-1 small fw-semibold text-break" , text: heading } ),
      table,
    ] } );
    return { node: node , layout: o.layout , roles: roles };
  },

  // The colour through the DOM: the CSP has no inline style attributes.
  swatch( color ) {
    const node = Dom.el( "span" , { class: "channels-swatch flex-shrink-0" , attrs: { "aria-hidden": "true" } } );
    node.style.backgroundColor = color;
    return node;
  },

  showError( text ) {
    const error = Dom.get( "channels-error" );
    Dom.text( error , text );
    Dom.show( error , Boolean( text ) );
  },

  submit() {
    for ( const b of this.blocks ) {
      if ( !b.roles.some( ( r ) => r.role === "ais" ) ) {
        this.showError( I18n.get( "channels.need_ais" ).replace( "{names}" , b.layout.names.join( " · " ) ) );
        return;
      }
      if ( b.roles.some( ( r ) => r.role === "other" && !r.label.trim() ) ) {
        this.showError( I18n.get( "channels.need_label" ) );
        return;
      }
    }
    if ( this.stacksAsked && !Dom.get( "channels-form" ).reportValidity() ) return;
    const answer = this.answer;
    this.answer = null;
    answer( {
      channels: this.blocks.map( ( b ) => ( { layout: b.layout , roles: b.roles.map( ( r ) => ( { role: r.role , label: r.label.trim() } ) ) } ) ),
      // The plane is the AIS role of the stacks' layout, which the server
      // applies; 0 stands for greyscale slices, which have only one.
      stack: this.stacksAsked ? { plane: 0 , z_step_um: Number( Dom.get( "batches-stack-z" ).value ) ,
        pixel_um: Number( Dom.get( "batches-stack-pixel" ).value ) } : null,
    } );
    this.modal.hide();
  },
};
