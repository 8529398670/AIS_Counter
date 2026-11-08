// The Measure tool on the Process screen (the toolbar's Measure, or M): how
// far each accepted AIS starts from its soma, kept on the AIS's row
// (soma_um, soma_px and the two ends; POST /api/ais/results/<id>/soma,
// app/models/ais.set_soma). An edit of the trace drops it: the start may move.
//
// It walks the batch's saved AIS one by one, in their numbers' order and on
// to the next image after an image's last. Each is drawn thick, the view
// zooms to its start site (the trace's first pixel, the end at its click),
// and its two ends are placed:
//
// - AIS end "preset": A starts on the trace's start; a click places the soma
//   end B. S (Other end) puts A on the trace's other end instead, for a trace
//   whose start is not the end nearer the soma.
// - AIS end "click": a click places A, the next B.
//
// With "soma hint" on, a .czi's soma outlines (app/analysis/soma.py) put B on
// the nearest outline point to A, for Enter to take or a click to move.
// One end is selected (ringed): a press on an end selects it and drags it,
// a click elsewhere moves it there, arrow keys nudge it (Shift: 5 px), Tab
// switches ends and Esc lets go (then arrows switch images again).
// Enter saves and moves on, N skips, [ and ] step. The tool stays on until
// T, E or D (or Done) picks another.
//
// On an image without saved AIS, and on every image in Manual (the panel's
// third mode), two clicks draw a line, saved as it is drawn: as many as
// wanted, numbered per image, each with an optional label
// (/api/ais/measurements, app/models/ais.add_measurement). Their ends drag and
// nudge the same way. They have nothing to do with any AIS and export on their
// own (measurements.csv, the report's Measurements sheet). In Manual [ and ]
// step through every image; leaving it goes to the next AIS not yet measured.
//
// Each free line gets the Type picked in the panel (the team's list, GET
// /api/ais/measure-types; admins edit it there): it stays on, here in this
// browser, until another is picked, so a run of soma distances is tagged as
// it is drawn. A line's own type can be changed in the list.
//
// Points are in MATLAB axes like everything in ais.js: pixel x's centre is x.
// The options (loupe, snap, ...) are remembered in this browser only, like
// Settings.
const MEASURE_COLOUR = "rgba(255, 80, 220, 1)";
const MEASURE_SAVED = "rgba(255, 80, 220, 0.6)";
const NUDGE_SAVE_MS = 400;  // how long after the last arrow key a recorded line saves
const LOUPE_PIXELS = 15;    // image pixels across the loupe
const LOUPE_SIZE = 160;     // its CSS size, px

const AisMeasure = {
  storageKey: "measure-options",
  // ais_end: preset | click | manual (no AIS: lines on any image); zoom: times
  // the whole-image view.
  defaults: { loupe: true , loupe_traces: true , snap: true , units: false , ais_end: "preset" , soma_hint: true , zoom: 4 ,
    measure_type: "" },
  types: [],          // the team's measurement types, for the Type picker
  options: null,
  on: false,
  row: null,          // the saved AIS being measured, or null: free lines, each recorded
  a: null,            // its ends, [x, y]; a free line's first click
  b: null,
  end: "first",       // which end of the trace A started on: "first" (its start) | "last" (S swapped it)
  sel: null,          // the end selected: { line: null (the AIS measured) | a recorded line , end: "a" | "b" }
  dragging: false,
  cursor: null,       // the pointer, MATLAB axes, while over the image
  aisEnd: "preset",   // the AIS mode Manual came from
  want: null,         // the row to pick once the next image is shown: "first" | "last" | an id
  saving: false,
  nudged: null,       // the recorded line an arrow key moved, its save waiting
  nudgeTimer: null,
  listKey: null,      // what the panel's list of recorded lines shows now

  init() {
    this.options = this.load();
    this.loupe = Dom.get( "ais-loupe" );
    Dom.all( "[data-measure-option]" ).forEach( ( control ) => {
      const field = control.dataset.measureOption;
      if ( control.type === "checkbox" ) control.checked = this.options[ field ];
      else if ( control.type === "radio" ) control.checked = control.value === this.options[ field ];
      else control.value = String( this.options[ field ] );
      control.addEventListener( "change" , () => {
        const was = this.options[ field ];
        if ( control.type === "checkbox" ) this.options[ field ] = control.checked;
        else if ( control.type === "radio" ) { if ( control.checked ) this.options[ field ] = control.value; }
        else this.options[ field ] = Number( control.value );
        this.save();
        if ( field === "ais_end" ) {
          control.blur();   // keys typed in a control do not reach the tool
          if ( was === "manual" || this.manual() ) this.modeChanged( was );
          else if ( this.row && this.row.soma_um == null ) this.select( this.row , false );
        }
        if ( field === "zoom" && this.row ) this.focus();
        Ais.draw();
        this.render();
      } );
    } );
    Dom.get( "ais-measure-prev" ).addEventListener( "click" , () => this.go( -1 ) );
    Dom.get( "ais-measure-next" ).addEventListener( "click" , () => this.go( 1 ) );
    Dom.get( "ais-measure-save" ).addEventListener( "click" , () => this.saveAndNext() );
    Dom.get( "ais-measure-skip" ).addEventListener( "click" , () => this.go( 1 ) );
    Dom.get( "ais-measure-clear" ).addEventListener( "click" , () => this.clear() );
    Dom.get( "ais-measure-swap" ).addEventListener( "click" , () => this.swapEnd() );
    Dom.get( "ais-measure-stop" ).addEventListener( "click" , () => Ais.setTool( "trace" ) );
    const picker = Dom.get( "ais-measure-type" );
    picker.addEventListener( "change" , () => {
      this.options.measure_type = picker.value;
      this.save();
      picker.blur();   // keys typed in a control do not reach the tool
    } );
    Dom.get( "ais-measure-types-edit" ).addEventListener( "click" , () => this.editTypes( true ) );
    Dom.get( "ais-measure-types-cancel" ).addEventListener( "click" , () => this.editTypes( false ) );
    Dom.get( "ais-measure-types-save" ).addEventListener( "click" , () => this.saveTypes() );
    this.loadTypes();
  },

  // --- measurement types ---------------------------------------------------

  async loadTypes() {
    try {
      this.types = ( await Api.request( "/api/ais/measure-types" ) ).types;
    } catch ( error ) {
      this.types = [];   // offline or refused: lines go untyped
    }
    this.renderTypes();
  },

  // The picker: no type, the team's, and the one last used if it has since
  // left the list (it stays picked until another is).
  renderTypes() {
    const picker = Dom.get( "ais-measure-type" );
    const names = this.types.slice();
    const current = this.options.measure_type;
    if ( current && !names.includes( current ) ) names.push( current );
    picker.replaceChildren( Dom.el( "option" , { attrs: { value: "" } , text: I18n.get( "ais.measure_type_none" ) } ) ,
      ...names.map( ( name ) => Dom.el( "option" , { attrs: { value: name } , text: name } ) ) );
    picker.value = current;
    Dom.show( Dom.get( "ais-measure-types-edit" ) , Boolean( Ais.me && Ais.me.role === "admin" ) );
    this.listKey = null;
    this.renderList();
  },

  editTypes( open ) {
    const box = Dom.get( "ais-measure-types-box" );
    Dom.show( box , open );
    if ( !open ) return;
    const text = Dom.get( "ais-measure-types-text" );
    text.value = this.types.join( "\n" );
    text.focus();
  },

  async saveTypes() {
    const names = Dom.get( "ais-measure-types-text" ).value.split( "\n" ).map( ( t ) => t.trim() ).filter( Boolean );
    try {
      this.types = ( await Api.post( "/api/ais/measure-types" , { types: names } ) ).types;
    } catch ( error ) {
      Ais.status( error.message , true );
      return;
    }
    this.editTypes( false );
    this.renderTypes();
  },

  load() {
    let stored = {};
    try {
      stored = JSON.parse( window.localStorage.getItem( this.storageKey ) || "{}" ) || {};
    } catch ( error ) {
      stored = {};   // storage blocked or garbled: defaults
    }
    const out = Object.assign( {} , this.defaults );
    Object.keys( this.defaults ).forEach( ( field ) => {
      if ( typeof stored[ field ] === typeof this.defaults[ field ] ) out[ field ] = stored[ field ];
    } );
    if ( ![ "preset" , "click" , "manual" ].includes( out.ais_end ) ) out.ais_end = this.defaults.ais_end;
    if ( ![ 2 , 4 , 8 ].includes( out.zoom ) ) out.zoom = this.defaults.zoom;
    return out;
  },

  save() {
    try {
      window.localStorage.setItem( this.storageKey , JSON.stringify( this.options ) );
    } catch ( error ) { /* storage blocked: kept for this visit */ }
  },

  // --- the tool turning on and off, and images changing --------------------

  start() {
    this.on = true;
    const rows = this.rows();
    this.want = null;
    const row = this.manual() ? null : rows.find( ( r ) => r.soma_um == null ) || rows[ 0 ] || null;
    if ( row ) this.select( row , true );
    else this.select( null , false );
  },

  reset() {
    this.flushNudge();
    this.on = false;
    this.row = null;
    this.a = null;
    this.b = null;
    this.sel = null;
    this.dragging = false;
    this.cursor = null;
    this.want = null;
    Ais.canvas.classList.remove( "ais-measure-grab" , "ais-measure-dragging" );
    this.renderLoupe();
    this.render();
  },

  // Ais.show: a new image, not drawn yet. The row to measure is picked now;
  // the view moves to it once the image is in (imageLoaded).
  imageShown() {
    if ( !this.on ) return;
    this.flushNudge();
    const rows = this.manual() ? [] : this.rows();
    const want = this.want;
    this.want = null;
    let row = null;
    if ( want === "last" ) row = rows[ rows.length - 1 ];
    else if ( want != null && want !== "first" ) row = rows.find( ( r ) => r.id === want );
    this.select( row || rows[ 0 ] || null , false );
  },

  imageLoaded() {
    if ( !this.on ) return;
    if ( this.row ) this.focus();
    this.hint();
  },

  // A saved AIS of the table (its Soma cell): measure it, on its image.
  measureRow( row ) {
    if ( !Ais.batch || row.batch_id !== Ais.batch.id ) return;
    const index = Ais.images.findIndex( ( entry ) => entry.key === row.image );
    if ( index < 0 ) return;
    if ( this.manual() ) this.leaveManual();
    if ( Ais.tool !== "measure" ) Ais.setTool( "measure" );
    if ( index === Ais.index ) {
      this.select( Ais.batchRows.find( ( r ) => r.id === row.id ) || row , true );
      return;
    }
    this.want = row.id;
    Ais.show( index , true );
  },

  // The image on screen's saved AIS, by number.
  rows() {
    const entry = Ais.images[ Ais.index ];
    return entry ? Ais.savedRows( entry ).slice().sort( ( p , q ) => p.n - q.n ) : [];
  },

  // Make row the one measured: its saved ends, else A on its start (preset)
  // and B on the nearest soma (hint), else nothing yet.
  select( row , focus ) {
    this.row = row;
    this.a = null;
    this.b = null;
    this.end = "first";
    if ( row && row.soma_um != null ) {
      this.a = [ row.soma_ais_x , row.soma_ais_y ];
      this.b = [ row.soma_x , row.soma_y ];
      const last = this.startOf( row , "last" );
      if ( row.pixels && row.pixels.length > 1 && last[ 0 ] === this.a[ 0 ] && last[ 1 ] === this.a[ 1 ] ) this.end = "last";
    } else if ( row && this.options.ais_end === "preset" ) {
      this.a = this.startOf( row );
      this.b = this.suggest( this.a );
    }
    this.sel = this.b ? { line: null , end: "b" } : null;
    if ( focus ) this.focus();
    this.hint();
    Ais.draw();
    this.render();
  },

  // The start site: the trace's first pixel (the end at its click), or with
  // end "last" its last.
  startOf( row , end ) {
    const pixels = row.pixels || [];
    const p = ( end || this.end ) === "last" ? pixels[ pixels.length - 1 ] : pixels[ 0 ];
    return p ? [ p[ 0 ] , p[ 1 ] ] : [ row.click_x , row.click_y ];
  },

  // S / Other end: A on the trace's other end, the view there, and (hint on)
  // B on the soma nearest it.
  swapEnd() {
    if ( !this.row ) return;
    this.end = this.end === "last" ? "first" : "last";
    this.a = this.startOf( this.row );
    const b = this.suggest( this.a );
    if ( b ) this.b = b;
    this.sel = this.b ? { line: null , end: "b" } : null;
    this.focus();
    Ais.draw();
    this.render();
  },

  // Centre the view on the AIS's A (else its start), zoomed options.zoom
  // times the whole image. A locked view stays as it is.
  focus() {
    if ( !this.row || !Ais.bitmap || Ais.locked ) return;
    const w = Ais.canvas.clientWidth;
    const h = Ais.canvas.clientHeight;
    if ( !w || !h ) return;
    const p = this.a || this.startOf( this.row );
    const fit = Math.min( w / Ais.bitmap.width , h / Ais.bitmap.height );
    const scale = Math.min( 40 , Math.max( 0.05 , fit * this.options.zoom ) );
    Ais.view = { scale: scale , ox: w / 2 - ( p[ 0 ] - 0.5 ) * scale , oy: h / 2 - ( p[ 1 ] - 0.5 ) * scale };
    Ais.draw();
  },

  // On a .czi with the hint on, load its somata (once) and put an unplaced
  // B on the nearest.
  hint() {
    const entry = Ais.images[ Ais.index ];
    if ( !this.on || !this.options.soma_hint || !entry || Ais.kind( entry ) !== "czi" ) return;
    const index = Ais.index;
    Ais.loadSomata( entry , index ).then( () => {
      if ( Ais.index !== index || !this.row || !this.a || this.b ) return;
      this.b = this.suggest( this.a );
      if ( this.b && !this.sel ) this.sel = { line: null , end: "b" };
      Ais.draw();
      this.render();
    } );
  },

  // The soma outline point nearest p, when the hint is on and there are any.
  suggest( p ) {
    if ( !p || !this.options.soma_hint || !Ais.somata || !Ais.somata.length ) return null;
    let best = null;
    let bestD = Infinity;
    Ais.somata.forEach( ( outline ) => outline.forEach( ( q ) => {
      const d = ( q[ 0 ] - p[ 0 ] ) ** 2 + ( q[ 1 ] - p[ 1 ] ) ** 2;
      if ( d < bestD ) {
        bestD = d;
        best = [ q[ 0 ] , q[ 1 ] ];
      }
    } ) );
    return best;
  },

  // --- stepping and saving -------------------------------------------------

  // The next (or previous) AIS: on this image, else the nearest image that
  // has any.
  go( delta ) {
    if ( this.manual() ) {
      this.goImage( delta );
      return;
    }
    const rows = this.rows();
    const at = this.row ? rows.indexOf( this.row ) : ( delta > 0 ? -1 : rows.length );
    const next = rows[ at + delta ];
    if ( next ) {
      this.select( next , true );
      return;
    }
    const shown = Ais.included();
    const order = delta > 0 ? shown.filter( ( i ) => i > Ais.index ) : shown.filter( ( i ) => i < Ais.index ).reverse();
    const index = order.find( ( i ) => Ais.savedRows( Ais.images[ i ] ).length );
    if ( index == null ) {
      Ais.status( I18n.get( delta > 0 ? "ais.measure_last" : "ais.measure_first" ) , true );
      return;
    }
    this.want = delta > 0 ? "first" : "last";
    Ais.show( index , true );
  },

  // Manual: the next (or previous) image, AIS or not.
  goImage( delta ) {
    const shown = Ais.included();
    const order = delta > 0 ? shown.filter( ( i ) => i > Ais.index ) : shown.filter( ( i ) => i < Ais.index ).reverse();
    if ( !order.length ) {
      Ais.status( I18n.get( delta > 0 ? "ais.measure_last_image" : "ais.measure_first_image" ) , true );
      return;
    }
    Ais.show( order[ 0 ] , true );
  },

  // The two ends' distance, px and µm, rounded as stored.
  distance( a , b ) {
    const px = Math.hypot( b[ 0 ] - a[ 0 ] , b[ 1 ] - a[ 1 ] );
    return { px: Math.round( px * 1000 ) / 1000 , um: Math.round( px * Ais.pixconvFor( Ais.images[ Ais.index ] ) * 10000 ) / 10000 };
  },

  // Whether what is placed is not what the row has saved.
  changed() {
    const r = this.row;
    if ( !r || !this.a || !this.b ) return false;
    return r.soma_um == null || r.soma_ais_x !== this.a[ 0 ] || r.soma_ais_y !== this.a[ 1 ]
      || r.soma_x !== this.b[ 0 ] || r.soma_y !== this.b[ 1 ];
  },

  async saveAndNext() {
    if ( this.saving || !this.row ) return;
    if ( this.changed() ) {
      const d = this.distance( this.a , this.b );
      const ok = await this.post( { soma_um: d.um , soma_px: d.px , soma_ais_x: this.a[ 0 ] , soma_ais_y: this.a[ 1 ] ,
        soma_x: this.b[ 0 ] , soma_y: this.b[ 1 ] } );
      if ( !ok ) return;
    }
    this.go( 1 );
  },

  async clear() {
    if ( this.saving || !this.row ) return;
    if ( this.row.soma_um != null && !( await this.post( null ) ) ) return;
    this.select( this.row , false );
  },

  async post( soma ) {
    this.saving = true;
    this.render();
    try {
      this.row = await Ais.postSoma( this.row , soma );
      return true;
    } catch ( error ) {
      Ais.status( error.message , true );
      return false;
    } finally {
      this.saving = false;
      Ais.renderTable();
      this.render();
    }
  },

  // --- Manual, and the lines recorded -------------------------------------

  manual() {
    return Boolean( this.options && this.options.ais_end === "manual" );
  },

  // Into or out of Manual: what was half placed goes. Into it, free lines on
  // this image; out of it, the AIS walk where it is needed.
  modeChanged( was ) {
    if ( was !== "manual" ) this.aisEnd = was;
    this.dropPlaced();
    if ( !this.on ) return;
    if ( this.manual() ) this.start();
    else this.resume();
  },

  dropPlaced() {
    this.flushNudge();
    this.a = null;
    this.b = null;
    this.sel = null;
  },

  // Back to the AIS mode Manual came from, for a row about to be picked.
  leaveManual() {
    this.options.ais_end = this.aisEnd;
    this.save();
    Dom.all( "[data-measure-option=ais_end]" ).forEach( ( radio ) => { radio.checked = radio.value === this.aisEnd; } );
    this.dropPlaced();
  },

  // The first AIS not yet measured: on this image, else the next image that
  // has one, round to the start of the batch. All measured: as Measure opens.
  resume() {
    const todo = ( i ) => Ais.savedRows( Ais.images[ i ] ).slice().sort( ( p , q ) => p.n - q.n ).find( ( r ) => r.soma_um == null );
    const shown = Ais.included();
    if ( Ais.index < 0 || todo( Ais.index ) ) {
      this.start();
      return;
    }
    const index = shown.filter( ( i ) => i > Ais.index ).concat( shown.filter( ( i ) => i < Ais.index ) ).find( ( i ) => todo( i ) );
    if ( index == null ) {
      this.start();
      return;
    }
    this.want = todo( index ).id;
    Ais.show( index , true );
  },

  recorded() {
    const entry = Ais.images[ Ais.index ];
    return entry ? Ais.measurementsOn( entry ) : [];
  },

  // A line's numbers from where its ends are now, at today's pixel size. Only
  // moving an end changes them: a new label leaves its length as measured.
  placed( line ) {
    const d = this.distance( line.a , line.b );
    return { a_x: line.a[ 0 ] , a_y: line.a[ 1 ] , b_x: line.b[ 0 ] , b_y: line.b[ 1 ] ,
      length_px: d.px , length_um: d.um , pixconv: Ais.pixconvFor( Ais.images[ Ais.index ] ) };
  },

  // What the server keeps of a line.
  fields( line ) {
    return { a_x: line.a_x , a_y: line.a_y , b_x: line.b_x , b_y: line.b_y , length_px: line.length_px ,
      length_um: line.length_um , pixconv: line.pixconv , label: line.label , type: line.type || "" };
  },

  // A line's own name in the outbox: the client_id it was made with, or its
  // server id for one recorded before lines had one.
  lineKey( line ) {
    return line.client_id || "m" + line.id;
  },

  // The outbox's answers about lines (outbox.js): the server's numbers for
  // a line once it arrives, and the lines as saved once something is refused.
  outboxHandler() {
    const owned = [ "id" , "n" , "rev" , "created_by" , "created_at" , "edited_at" , "edited_by" , "batch_name" ];
    return {
      reply: ( item , out ) => {
        const line = Ais.measurements.find( ( other ) => this.lineKey( other ) === item.key );
        if ( line && out && item.kind !== "delete" ) owned.forEach( ( k ) => { if ( k in out ) line[ k ] = out[ k ]; } );
        if ( item.kind === "delete" && out && out.renumbered ) {
          const n = new Map( out.renumbered.map( ( r ) => [ r.id , r.n ] ) );
          Ais.measurements.forEach( ( other ) => { if ( n.has( other.id ) ) other.n = n.get( other.id ); } );
        }
        this.render();
      },
      resync: () => this.writeFailed(),
    };
  },

  // Refused by the server (outbox.js said why): back to what it has.
  async writeFailed() {
    this.sel = null;
    if ( Ais.batch ) await Ais.loadMeasurements();
    Ais.draw();
    Ais.renderTable();
  },

  // Shown at once, and sent when the server can be reached; a drag straight
  // after is queued behind it and finds its id.
  addLine( a , b ) {
    const entry = Ais.images[ Ais.index ];
    if ( !entry || !Ais.batch ) return;
    const same = Ais.measurementsOn( entry );
    const line = { a: a , b: b , image: entry.key , batch_id: Ais.batch.id , batch_name: Ais.batch.name , label: "" ,
      type: this.options.measure_type , n: same.length ? same[ same.length - 1 ].n + 1 : 1 ,
      id: null , rev: 0 , client_id: Outbox.newId() };
    Object.assign( line , this.placed( line ) );
    Ais.measurements.push( line );
    Ais.renderTable();
    Outbox.add( { kind: "create" , bucket: "measurements" , key: line.client_id , path: "/api/ais/measurements" ,
      label: this.what( line ) ,
      body: { batch_id: line.batch_id , image: line.image , measurement: this.fields( line ) , client_id: line.client_id } } );
  },

  saveLine( line ) {
    if ( !line.dirty || line.gone ) return;
    line.dirty = false;
    Outbox.add( { kind: "update" , bucket: "measurements" , key: this.lineKey( line ) ,
      path: "/api/ais/measurements/{id}/update" , label: this.what( line ) , body: { measurement: this.fields( line ) } } ,
    { id: line.id , rev: line.rev } );
  },

  // How a refusal names the line: its image and number.
  what( line ) {
    return ( I18n.get( "outbox.line" ) || "line {n} on {image}" ).replace( "{n}" , line.n ).replace( "{image}" , line.image );
  },

  // Arrow keys come fast: save once they stop.
  nudgeLater( line ) {
    if ( this.nudged && this.nudged !== line ) this.flushNudge();
    this.nudged = line;
    window.clearTimeout( this.nudgeTimer );
    this.nudgeTimer = window.setTimeout( () => this.flushNudge() , NUDGE_SAVE_MS );
  },

  flushNudge() {
    window.clearTimeout( this.nudgeTimer );
    const line = this.nudged;
    this.nudged = null;
    if ( line ) this.saveLine( line );
  },

  setLabel( line , label ) {
    line.label = label;
    line.dirty = true;
    this.saveLine( line );
  },

  setType( line , type ) {
    line.type = type;
    line.dirty = true;
    this.saveLine( line );
  },

  deleteLine( line ) {
    if ( !line ) return;
    if ( this.nudged === line ) this.flushNudge();
    line.gone = true;
    Ais.measurements = Ais.measurements.filter( ( other ) => other !== line );
    if ( this.sel && this.sel.line === line ) this.sel = null;
    // The rest of its image close up, as the server renumbers them.
    const entry = Ais.images[ Ais.index ];
    if ( entry ) Ais.measurementsOn( entry ).forEach( ( other , i ) => { other.n = i + 1; } );
    Ais.renderTable();
    Ais.draw();
    Outbox.add( { kind: "delete" , bucket: "measurements" , key: this.lineKey( line ) ,
      path: "/api/ais/measurements/{id}/delete" , label: this.what( line ) , body: {} } , { id: line.id , rev: line.rev } );
  },

  // The pill on a recorded line, and how far it is in the panel's list.
  lineUm( line ) {
    return line.length_um.toFixed( 2 ) + " µm";
  },

  lineText( line ) {
    const parts = [ String( line.n ) + ":" , this.lineUm( line ) ];
    if ( this.options.units ) parts.push( "· " + line.length_px.toFixed( 1 ) + " px" );
    if ( line.type ) parts.push( "· " + line.type );
    if ( line.label ) parts.push( "· " + line.label );
    return parts.join( " " );
  },

  // --- the pointer and keys ------------------------------------------------

  // A canvas point (ais.js toImage) in MATLAB axes: the pixel's centre when
  // snapping.
  point( p ) {
    if ( this.options.snap ) return [ Math.floor( p.x ) + 1 , Math.floor( p.y ) + 1 ];
    return [ Math.round( ( p.x + 0.5 ) * 100 ) / 100 , Math.round( ( p.y + 0.5 ) * 100 ) / 100 ];
  },

  near( p , q ) {
    const reach = Math.max( 1.5 , 8 / Ais.view.scale );
    return q && Math.hypot( p[ 0 ] - q[ 0 ] , p[ 1 ] - q[ 1 ] ) <= reach;
  },

  // An end of the AIS measured, or (no AIS) of a recorded line, and setting it.
  endOf( sel ) { return sel.line ? sel.line[ sel.end ] : this[ sel.end ]; },
  setEnd( sel , p ) {
    if ( sel.line ) {
      sel.line[ sel.end ] = p;
      Object.assign( sel.line , this.placed( sel.line ) , { dirty: true } );
    } else {
      this[ sel.end ] = p;
    }
  },

  // The end within reach of a canvas point, nearest first, or null.
  hit( point ) {
    if ( !point ) return null;
    const p = [ point.x + 0.5 , point.y + 0.5 ];
    const ends = [];
    if ( this.row ) {
      if ( this.b ) ends.push( { line: null , end: "b" } );
      if ( this.a ) ends.push( { line: null , end: "a" } );
    } else {
      this.recorded().slice().reverse()
        .forEach( ( line ) => ends.push( { line: line , end: "b" } , { line: line , end: "a" } ) );
    }
    let best = null;
    let bestD = Infinity;
    ends.forEach( ( sel ) => {
      const q = this.endOf( sel );
      const d = Math.hypot( p[ 0 ] - q[ 0 ] , p[ 1 ] - q[ 1 ] );
      if ( this.near( p , q ) && d < bestD ) {
        bestD = d;
        best = sel;
      }
    } );
    return best;
  },

  same( p , q ) {
    return Boolean( p && q && p.line === q.line && p.end === q.end );
  },

  // ais.js pointerdown: on an end, select it and drag it (true: no panning).
  onDown( point ) {
    const sel = this.on && !( this.a && !this.b && !this.row ) ? this.hit( point ) : null;
    if ( !sel ) return false;
    this.sel = sel;
    this.dragging = true;
    Ais.canvas.classList.add( "ais-measure-dragging" );
    this.cursor = this.endOf( sel );
    Ais.draw();
    this.render();
    return true;
  },

  onDrag( point ) {
    if ( !this.dragging || !this.sel ) return;
    const p = this.clamp( this.point( point ) );
    this.setEnd( this.sel , p );
    this.cursor = p;
    Ais.draw();
    this.render();
  },

  onUp() {
    this.dragging = false;
    Ais.canvas.classList.remove( "ais-measure-dragging" );
    if ( this.sel && this.sel.line ) this.saveLine( this.sel.line );
    Ais.draw();
    this.render();
  },

  // Kept on the image.
  clamp( p ) {
    const bitmap = Ais.bitmap;
    if ( !bitmap ) return p;
    return [ Math.min( bitmap.width + 0.5 , Math.max( 0.5 , p[ 0 ] ) ) , Math.min( bitmap.height + 0.5 , Math.max( 0.5 , p[ 1 ] ) ) ];
  },

  // A click that is not on an end (a press on one selects it, onDown): the
  // selected end moves there; else the next end is placed.
  onClick( point ) {
    const p = this.point( point );
    if ( this.row ) {
      if ( this.sel ) {
        this.setEnd( this.sel , p );
      } else if ( !this.a ) {
        this.a = p;
        this.b = this.suggest( p );
        if ( this.b ) this.sel = { line: null , end: "b" };
      } else if ( !this.b ) {
        this.b = p;
        this.sel = { line: null , end: "b" };
      } else if ( this.options.ais_end === "click" ) {
        this.a = p;
        this.b = this.suggest( p );
        this.sel = this.b ? { line: null , end: "b" } : null;
      } else {
        this.b = p;
        this.sel = { line: null , end: "b" };
      }
    } else {
      // Always the next line: a selected end lets go rather than jumps here.
      this.flushNudge();
      this.sel = null;
      if ( !this.a ) {
        this.a = p;
      } else {
        this.addLine( this.a , p );
        this.a = null;
      }
    }
    Ais.draw();
    this.render();
  },

  // point: canvas units, or null (off the canvas, or panning).
  onMove( point ) {
    const bitmap = Ais.bitmap;
    const inside = point && bitmap && point.x >= 0 && point.y >= 0 && point.x < bitmap.width && point.y < bitmap.height;
    this.cursor = inside ? this.point( point ) : null;
    Ais.canvas.classList.toggle( "ais-measure-grab" , Boolean( inside && this.hit( point ) ) );
    if ( this.rubber() ) Ais.draw();
    else this.renderLoupe();
  },

  // A line follows the pointer: only one end placed.
  rubber() {
    return Boolean( this.a && !this.b );
  },

  // Arrow keys: the selected end, 1 px (Shift 5), or 0.1 (Shift 1) unsnapped.
  nudge( dx , dy , big ) {
    const step = this.options.snap ? ( big ? 5 : 1 ) : ( big ? 1 : 0.1 );
    const q = this.endOf( this.sel );
    const p = this.clamp( [ q[ 0 ] + dx * step , q[ 1 ] + dy * step ] );
    this.setEnd( this.sel , [ Math.round( p[ 0 ] * 100 ) / 100 , Math.round( p[ 1 ] * 100 ) / 100 ] );
    this.cursor = this.endOf( this.sel );
    if ( this.sel.line ) this.nudgeLater( this.sel.line );
    Ais.draw();
    this.render();
  },

  onKey( event ) {
    if ( Ais.tool !== "measure" ) return false;
    const is = ( action ) => Shortcuts.is( event , "measure." + action );
    const nudges = { left: [ -1 , 0 ] , right: [ 1 , 0 ] , up: [ 0 , -1 ] , down: [ 0 , 1 ] };
    const nudge = Object.keys( nudges ).find( ( way ) => is( "nudge_" + way ) || is( "nudge_big_" + way ) );
    if ( nudge && this.sel ) {
      event.preventDefault();
      this.nudge( nudges[ nudge ][ 0 ] , nudges[ nudge ][ 1 ] , is( "nudge_big_" + nudge ) );
      return true;
    }
    if ( is( "switch_end" ) && ( this.sel || this.a || this.b ) ) {
      event.preventDefault();
      const line = this.sel ? this.sel.line : null;
      const other = this.sel && this.sel.end === "b" ? "a" : "b";
      if ( line || this[ other ] ) this.sel = { line: line , end: other };
      Ais.draw();
      this.render();
      return true;
    }
    if ( is( "let_go" ) ) {
      if ( this.sel ) this.sel = null;
      else if ( this.a && !this.b && !( this.row && this.options.ais_end === "preset" ) ) this.a = null;
      else return false;
      event.preventDefault();
      Ais.draw();
      this.render();
      return true;
    }
    if ( is( "delete_line" ) ) {
      event.preventDefault();
      if ( this.row ) {
        this.b = null;
        this.sel = null;
      } else {
        const lines = this.recorded();
        this.deleteLine( this.sel ? this.sel.line : lines[ lines.length - 1 ] );
      }
      Ais.draw();
      this.render();
      return true;
    }
    const step = is( "next_ais" ) ? 1 : is( "prev_ais" ) ? -1 : 0;
    if ( !this.row ) {
      if ( step ) { event.preventDefault(); this.go( step ); return true; }
      return false;
    }
    if ( is( "save_next" ) ) { event.preventDefault(); this.saveAndNext(); return true; }
    if ( is( "skip" ) ) { event.preventDefault(); this.go( 1 ); return true; }
    if ( is( "swap_end" ) ) { event.preventDefault(); this.swapEnd(); return true; }
    if ( step ) { event.preventDefault(); this.go( step ); return true; }
    return false;
  },

  // --- drawing -------------------------------------------------------------

  label( a , b ) {
    const d = this.distance( a , b );
    const um = d.um.toFixed( 2 ) + " µm";
    if ( !this.options.units ) return um;
    const dx = Math.abs( b[ 0 ] - a[ 0 ] );
    const dy = Math.abs( b[ 1 ] - a[ 1 ] );
    return um + " · " + d.px.toFixed( 1 ) + " px (Δx " + Ais.fmt( Number( dx.toFixed( 2 ) ) ) + ", Δy " + Ais.fmt( Number( dy.toFixed( 2 ) ) ) + ")";
  },

  // The lines to draw now: [{ a, b, colour, label }].
  shapes() {
    if ( !this.on ) return [];
    const out = [];
    const entry = Ais.images[ Ais.index ];
    if ( entry ) {
      Ais.savedRows( entry ).forEach( ( r ) => {
        if ( r === this.row || r.soma_um == null ) return;
        out.push( { a: [ r.soma_ais_x , r.soma_ais_y ] , b: [ r.soma_x , r.soma_y ] , colour: MEASURE_SAVED , label: true } );
      } );
    }
    const colour = this.row ? MEASURE_SAVED : MEASURE_COLOUR;
    this.recorded().forEach( ( line ) => out.push( { a: line.a , b: line.b , colour: colour , label: true , text: this.lineText( line ) } ) );
    const a = this.a;
    const b = this.b || ( this.a ? this.cursor : null );
    if ( a && b ) out.push( { a: a , b: b , colour: MEASURE_COLOUR , label: true , live: true } );
    return out;
  },

  // ais.js draw(): in image units, s screen px per image px.
  draw( ctx , s , lw ) {
    if ( !this.on ) {
      this.renderLoupe();
      return;
    }
    if ( this.row ) Ais.polyline( this.row.pixels , "rgba(255, 190, 0, 1)" , lw * 3 );
    const shapes = this.shapes();
    shapes.forEach( ( shape ) => this.paint( ctx , shape , lw , s ) );
    this.ends( ctx , s , lw );
    shapes.filter( ( shape ) => shape.label ).forEach( ( shape ) => this.pill( ctx , shape , s ) );
    this.renderLoupe();
  },

  paint( ctx , shape , lw , s ) {
    Ais.polyline( [ shape.a , shape.b ] , shape.colour , lw , ctx );
    [ shape.a , shape.b ].forEach( ( p ) => this.tick( ctx , p , shape.colour , 3 / s , lw ) );
  },

  // A small cross on an end, in its own context (the loupe draws them too).
  tick( ctx , p , colour , size , width ) {
    const x = p[ 0 ] - 0.5;
    const y = p[ 1 ] - 0.5;
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo( x - size , y ); ctx.lineTo( x + size , y );
    ctx.moveTo( x , y - size ); ctx.lineTo( x , y + size );
    ctx.stroke();
  },

  // A and B of the AIS measured (A white, B magenta), and a ring round the
  // end selected.
  ends( ctx , s , lw ) {
    const size = ( 5 + Settings.lineWidth() ) / s;
    if ( this.a ) this.tick( ctx , this.a , "rgba(255, 255, 255, 1)" , size , lw );
    if ( this.b ) this.tick( ctx , this.b , MEASURE_COLOUR , size , lw );
    if ( !this.sel ) return;
    const p = this.endOf( this.sel );
    if ( !p ) return;
    ctx.strokeStyle = this.sel.end === "a" && !this.sel.line ? "rgba(255, 255, 255, 1)" : MEASURE_COLOUR;
    ctx.lineWidth = lw * 1.5;
    ctx.beginPath();
    ctx.arc( p[ 0 ] - 0.5 , p[ 1 ] - 0.5 , 9 / s , 0 , 2 * Math.PI );
    ctx.stroke();
  },

  // The distance at the line's middle, white on a dark pill.
  pill( ctx , shape , s ) {
    const text = shape.text || this.label( shape.a , shape.b );
    const x = ( shape.a[ 0 ] + shape.b[ 0 ] ) / 2 - 0.5;
    const y = ( shape.a[ 1 ] + shape.b[ 1 ] ) / 2 - 0.5;
    ctx.font = ( 12 / s ) + "px sans-serif";
    const w = ctx.measureText( text ).width;
    const pad = 4 / s;
    const top = y - 22 / s;
    ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
    ctx.fillRect( x - w / 2 - pad , top , w + 2 * pad , 16 / s );
    ctx.fillStyle = "rgba(255, 255, 255, 1)";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText( text , x , top + 8 / s );
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
  },

  // The loupe: LOUPE_PIXELS image pixels around the pointer, big and sharp,
  // beside it, with the pixel under it boxed and its position below.
  renderLoupe() {
    const loupe = this.loupe;
    if ( !loupe ) return;
    const p = this.cursor;
    const show = this.on && this.options.loupe && p && Ais.bitmap;
    Dom.show( loupe , Boolean( show ) );
    if ( !show ) return;
    const dpr = window.devicePixelRatio || 1;
    const size = LOUPE_SIZE;
    if ( loupe.width !== Math.round( size * dpr ) ) {
      loupe.width = Math.round( size * dpr );
      loupe.height = Math.round( size * dpr );
    }
    // Beside the pointer, on whichever side has room.
    const v = Ais.view;
    const sx = ( p[ 0 ] - 0.5 ) * v.scale + v.ox;
    const sy = ( p[ 1 ] - 0.5 ) * v.scale + v.oy;
    const w = Ais.canvas.clientWidth;
    const h = Ais.canvas.clientHeight;
    const gap = 24;
    const left = sx + gap + size > w ? sx - gap - size : sx + gap;
    const top = sy + gap + size > h ? sy - gap - size : sy + gap;
    loupe.style.left = Math.max( 0 , left ) + "px";
    loupe.style.top = Math.max( 0 , top ) + "px";

    const ctx = loupe.getContext( "2d" );
    const k = size / LOUPE_PIXELS;
    const cx = p[ 0 ] - 0.5;
    const cy = p[ 1 ] - 0.5;
    ctx.setTransform( 1 , 0 , 0 , 1 , 0 , 0 );
    ctx.fillStyle = "#000";
    ctx.fillRect( 0 , 0 , loupe.width , loupe.height );
    ctx.setTransform( dpr * k , 0 , 0 , dpr * k , dpr * ( size / 2 - cx * k ) , dpr * ( size / 2 - cy * k ) );
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage( Ais.bitmap , 0 , 0 );
    // The pixel grid.
    const x0 = Math.floor( cx - LOUPE_PIXELS / 2 ) - 1;
    const y0 = Math.floor( cy - LOUPE_PIXELS / 2 ) - 1;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
    ctx.lineWidth = 1 / k;
    ctx.beginPath();
    for ( let i = 0; i <= LOUPE_PIXELS + 2; i += 1 ) {
      ctx.moveTo( x0 + i , y0 ); ctx.lineTo( x0 + i , y0 + LOUPE_PIXELS + 2 );
      ctx.moveTo( x0 , y0 + i ); ctx.lineTo( x0 + LOUPE_PIXELS + 2 , y0 + i );
    }
    ctx.stroke();
    // The traces as the image draws them: saved AIS green, the one measured amber.
    if ( this.options.loupe_traces ) {
      const entry = Ais.images[ Ais.index ];
      if ( entry ) Ais.savedRows( entry ).forEach( ( r ) => { if ( r !== this.row ) Ais.polyline( r.pixels , "rgba(60, 220, 120, 0.9)" , 1.5 / k , ctx ); } );
      if ( this.row ) Ais.polyline( this.row.pixels , "rgba(255, 190, 0, 1)" , 2.5 / k , ctx );
    }
    this.shapes().forEach( ( shape ) => this.paint( ctx , shape , 1.5 / k , k ) );
    this.ends( ctx , k , 1.5 / k );
    // The pixel under the pointer.
    const px = Math.floor( cx );
    const py = Math.floor( cy );
    ctx.strokeStyle = "rgba(255, 225, 0, 1)";
    ctx.lineWidth = 2 / k;
    ctx.strokeRect( px , py , 1 , 1 );
    // Where it is, 1-based like the rest of the app.
    ctx.setTransform( dpr , 0 , 0 , dpr , 0 , 0 );
    const text = "x " + ( px + 1 ) + ", y " + ( py + 1 );
    ctx.font = "11px sans-serif";
    ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
    ctx.fillRect( 0 , size - 18 , size , 18 );
    ctx.fillStyle = "#fff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText( text , size / 2 , size - 9 );
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
  },

  // --- the Measure panel ---------------------------------------------------

  render() {
    const panel = Dom.get( "ais-measure-panel" );
    if ( !panel ) return;
    Dom.show( panel , this.on );
    if ( !this.on ) return;
    const rows = this.rows();
    const r = this.row;
    const shown = Ais.included();
    const manual = this.manual();
    Dom.text( Dom.get( "ais-measure-title" ) , I18n.get( r ? "ais.measure_heading" : "ais.measure_lines_heading" ) );
    Dom.get( "ais-measure-prev" ).title = I18n.get( manual ? "ais.measure_prev_image" : "ais.measure_prev" );
    Dom.get( "ais-measure-next" ).title = I18n.get( manual ? "ais.measure_next_image" : "ais.measure_next" );
    let where = "";
    if ( !r ) {
      where = I18n.get( "ais.measure_record_where" ).replace( "{n}" , String( this.recorded().length ) )
        .replace( "{image}" , String( shown.indexOf( Ais.index ) + 1 ) ).replace( "{images}" , String( shown.length ) );
    } else {
      where = I18n.get( "ais.measure_where" ).replace( "{n}" , String( rows.indexOf( r ) + 1 ) ).replace( "{count}" , String( rows.length ) )
        .replace( "{image}" , String( shown.indexOf( Ais.index ) + 1 ) ).replace( "{images}" , String( shown.length ) );
    }
    Dom.text( Dom.get( "ais-measure-where" ) , where );
    let help;
    if ( !r ) help = I18n.get( this.a ? "ais.measure_ruler_second" : this.sel ? "ais.measure_lines_selected" : manual ? "ais.measure_manual_help" : "ais.measure_no_ais" );
    else if ( !this.a ) help = I18n.get( "ais.measure_click_start" );
    else if ( !this.b ) help = I18n.get( "ais.measure_click_soma" );
    else help = I18n.get( this.sel ? "ais.measure_selected" : "ais.measure_ready" );
    Dom.text( Dom.get( "ais-measure-help" ) , help );
    Dom.text( Dom.get( "ais-measure-end" ) , r ? I18n.get( this.end === "last" ? "ais.measure_end_last" : "ais.measure_end_first" ) : "" );
    Dom.get( "ais-measure-end" ).classList.toggle( "text-warning" , this.end === "last" );
    let value = "";
    if ( r && this.a && this.b ) value = this.label( this.a , this.b );
    Dom.text( Dom.get( "ais-measure-value" ) , value );
    const saved = r && r.soma_um != null ? I18n.get( "ais.measure_saved" ).replace( "{um}" , r.soma_um.toFixed( 2 ) ) : "";
    Dom.text( Dom.get( "ais-measure-saved" ) , saved );
    Dom.show( Dom.get( "ais-measure-actions" ) , Boolean( r ) );
    Dom.get( "ais-measure-save" ).disabled = this.saving || !( this.a && this.b );
    Dom.get( "ais-measure-clear" ).disabled = this.saving;
    Dom.show( Dom.get( "ais-measure-clear" ) , Boolean( r && ( r.soma_um != null || this.changed() ) ) );
    Dom.get( "ais-measure-prev" ).disabled = this.saving;
    Dom.get( "ais-measure-next" ).disabled = this.saving;
    Dom.show( Dom.get( "ais-measure-locked" ) , Boolean( r && Ais.locked ) );
    Dom.show( Dom.get( "ais-measure-type-row" ) , !r );
    this.renderList();
  },

  // Free lines: the image's, each with its label to fill in and a delete.
  // Left alone while a label is being typed in, or the typing would be lost.
  renderList() {
    const list = Dom.get( "ais-measure-list" );
    const lines = this.row ? [] : this.recorded();
    Dom.show( list , lines.length > 0 );
    const key = JSON.stringify( lines.map( ( line ) => [ line.id , line.n , line.label , line.type , line.length_um ] ) );
    const typing = list.contains( document.activeElement ) && [ "INPUT" , "SELECT" ].includes( document.activeElement.tagName );
    if ( key === this.listKey || typing ) return;
    this.listKey = key;
    list.replaceChildren( ...lines.map( ( line ) => {
      const input = Dom.el( "input" , { class: "form-control form-control-sm" ,
        attrs: { type: "text" , maxlength: "1000" , placeholder: I18n.get( "ais.measure_label" ) , "aria-label": I18n.get( "ais.measure_label" ) } } );
      input.value = line.label || "";
      input.addEventListener( "change" , () => {
        this.setLabel( line , input.value );
        Ais.draw();
      } );
      input.addEventListener( "blur" , () => this.render() );
      input.addEventListener( "keydown" , ( event ) => { if ( event.key === "Enter" ) input.blur(); } );
      const gone = Dom.el( "button" , { class: "btn btn-outline-danger btn-sm" ,
        attrs: { type: "button" , title: I18n.get( "ais.measure_delete_line" ) , "aria-label": I18n.get( "ais.measure_delete_line" ) } ,
        children: [ Dom.el( "i" , { class: "bi bi-x-lg" , attrs: { "aria-hidden": "true" } } ) ] } );
      gone.addEventListener( "click" , () => this.deleteLine( line ) );
      return Dom.el( "div" , { class: "ais-measure-line small" , children: [
        Dom.el( "span" , { class: "text-body-secondary" , text: String( line.n ) } ),
        Dom.el( "span" , { class: "ais-measure-line-um" , text: this.lineUm( line ) } ),
        this.typeSelect( line ) , input , gone ] } );
    } ) );
  },

  // A line's own type, to change after it was drawn.
  typeSelect( line ) {
    const names = this.types.slice();
    if ( line.type && !names.includes( line.type ) ) names.push( line.type );
    const select = Dom.el( "select" , { class: "form-select form-select-sm ais-measure-line-type" ,
      attrs: { "aria-label": I18n.get( "ais.measure_type" ) } ,
      children: [ Dom.el( "option" , { attrs: { value: "" } , text: I18n.get( "ais.measure_type_none" ) } ) ,
        ...names.map( ( name ) => Dom.el( "option" , { attrs: { value: name } , text: name } ) ) ] } );
    select.value = line.type || "";
    select.addEventListener( "change" , () => {
      this.setType( line , select.value );
      select.blur();
      Ais.draw();
    } );
    select.addEventListener( "blur" , () => this.render() );
    return select;
  },
};
