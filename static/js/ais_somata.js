// The somata as the Measure tool and the Soma button see them (POST
// /api/ais/files/<sha>/pair, app/analysis/pairing.py): each soma the largest
// ellipse inside its outline; and per saved AIS, the guess for its two ends
// (the thicker end, and B where the line from the ellipse's centre toward it
// meets the ellipse).
// One request per image, and again when its saved AIS change or Split flips.
//
// Split (the scissors beside Soma in the "What the image shows" bar,
// remembered in this browser): an outline holding several hotspots, touching
// cells, is one soma per hotspot; off, one per outline. The sliders there set
// what counts as a soma (shape, also remembered here): its longest diameter
// from min to max µm, and its roundness, the narrowest it may be across as a
// share of that (1: a circle). Each soma's ellipse is the largest inside it
// those allow; one too small for the min is no soma.
const SOMA_ELLIPSE = "rgba(255, 140, 40, 1)";
const SOMA_FAINT = "rgba(255, 140, 40, 0.35)";

const AisSomata = {
  storageKey: "soma-split",
  shapeKey: "soma-shape",
  split: true,
  defaults: { min_um: 6 , max_um: 40 , roundness: 0.6 },   // as pairing.SomaShape
  shape: null,
  state: null,       // { index , key (what was asked) , bodies , byKey: Map , promise }; bodies null while on its way
  listeners: [],     // called when guesses arrive

  init() {
    this.shape = Object.assign( {} , this.defaults );
    try {
      const stored = window.localStorage.getItem( this.storageKey );
      if ( stored === "0" || stored === "1" ) this.split = stored === "1";
      const shape = JSON.parse( window.localStorage.getItem( this.shapeKey ) || "null" );
      if ( shape && typeof shape === "object" ) this.shape = this.checked( Object.assign( {} , this.defaults , shape ) );
    } catch ( error ) { /* storage blocked or garbled: the defaults */ }
  },

  // A shape the server takes: numbers, 0 <= min < max <= 200, 0 <= roundness <= 1.
  checked( shape ) {
    const num = ( v , d ) => ( typeof v === "number" && Number.isFinite( v ) ? v : d );
    let min = Math.min( 199 , Math.max( 0 , num( shape.min_um , this.defaults.min_um ) ) );
    let max = Math.min( 200 , Math.max( 1 , num( shape.max_um , this.defaults.max_um ) ) );
    if ( max <= min ) max = Math.min( 200 , min + 1 );
    if ( max <= min ) min = max - 1;
    const roundness = Math.min( 1 , Math.max( 0 , num( shape.roundness , this.defaults.roundness ) ) );
    return { min_um: min , max_um: max , roundness: roundness };
  },

  // One of the shape's numbers changed (the sliders' fields); back as kept.
  setShape( changes ) {
    this.shape = this.checked( Object.assign( {} , this.shape , changes ) );
    try {
      window.localStorage.setItem( this.shapeKey , JSON.stringify( this.shape ) );
    } catch ( error ) { /* storage blocked: kept for this visit */ }
    this.ensure();
    return this.shape;
  },

  setSplit( on ) {
    this.split = on;
    try {
      window.localStorage.setItem( this.storageKey , on ? "1" : "0" );
    } catch ( error ) { /* storage blocked: kept for this visit */ }
    this.ensure();
  },

  // The measured AIS on a row's trace: its first and last trace points,
  // 1-based, where its profile crosses 33% (start_um and end_um over the
  // pixel size it was measured at, as service.shape reads them); null when
  // the row lacks them.
  section( row ) {
    const n = ( row.pixels || [] ).length;
    if ( !n || row.start_um == null || row.end_um == null || !row.pixconv ) return null;
    const first = Math.min( n , Math.max( 1 , Math.round( row.start_um / row.pixconv ) ) );
    const last = Math.min( n , Math.max( first , Math.round( row.end_um / row.pixconv ) ) );
    return [ first , last ];
  },

  pairKey( row ) {
    return row.id != null ? "id:" + row.id : "c:" + row.client_id;
  },

  // Ask for the image on screen unless what was asked still holds (the same
  // image, saved AIS and Split). A failure leaves no somata and no guesses.
  ensure() {
    const entry = Ais.images[ Ais.index ];
    const sha = entry ? Ais.sha( entry ) : null;
    if ( !sha ) return null;
    const rows = Ais.savedRows( entry ).filter( ( r ) => r.pixels && r.pixels.length );
    const shape = this.shape;
    const key = [ sha , this.split ? "split" : "whole" , shape.min_um , shape.max_um , shape.roundness , ...rows.map( ( r ) => this.pairKey( r ) + ":" + r.pixels.length + ":" + this.section( r ) ) ].join( "|" );
    if ( this.state && this.state.index === Ais.index && this.state.key === key ) return this.state.promise;
    const state = { index: Ais.index , key: key , bodies: null , byKey: null };
    this.state = state;
    state.promise = Api.post( "/api/ais/files/" + sha + "/pair" , { pixel_um: Ais.pixconvFor( entry ) , split: this.split , soma: shape ,
      traces: rows.map( ( r ) => {
        const section = this.section( r );
        return section ? { id: this.pairKey( r ) , pixels: r.pixels , section: section } : { id: this.pairKey( r ) , pixels: r.pixels };
      } ) } ).then( ( out ) => {
      if ( this.state !== state ) return state;
      state.bodies = out.bodies;
      state.byKey = new Map( out.pairs.map( ( p ) => [ p.id , p ] ) );
      this.listeners.forEach( ( fn ) => fn() );
      Ais.draw();
      return state;
    } ).catch( () => {
      if ( this.state === state ) {
        state.bodies = [];
        state.byKey = new Map();
      }
      return state;
    } );
    return state.promise;
  },

  current() {
    const s = this.state;
    return s && s.index === Ais.index && s.bodies ? s : null;
  },

  // The image's soma ellipses, or null (none asked for or arrived yet).
  bodies() {
    const s = this.current();
    return s ? s.bodies : null;
  },

  // A saved AIS's guess, or null.
  pair( row ) {
    const s = this.current();
    return s && row ? s.byKey.get( this.pairKey( row ) ) || null : null;
  },

  // As pairing.ray_hit: where the line from ellipse e's centre toward p
  // meets its edge, and whether p is inside.
  rayHit( e , p ) {
    const th = e.angle_deg * Math.PI / 180;
    const u = [ Math.cos( th ) , Math.sin( th ) ];
    const d = [ p[ 0 ] - e.cx , p[ 1 ] - e.cy ];
    const r = Math.hypot( d[ 0 ] , d[ 1 ] );
    const w = r ? [ d[ 0 ] / r , d[ 1 ] / r ] : u;
    const along = w[ 0 ] * u[ 0 ] + w[ 1 ] * u[ 1 ];
    const across = -w[ 0 ] * u[ 1 ] + w[ 1 ] * u[ 0 ];
    const t = 1 / Math.sqrt( ( along / e.a ) ** 2 + ( across / e.b ) ** 2 );
    const round = ( v ) => Math.round( v * 100 ) / 100;
    return { b: [ round( e.cx + t * w[ 0 ] ) , round( e.cy + t * w[ 1 ] ) ] , inside: r <= t };
  },

  // With Soma on: every ellipse, and a cross on its hotspot.
  draw( ctx , s , lw ) {
    if ( !Ais.showSomata ) return;
    this.ensure();
    const bodies = this.bodies();
    if ( bodies ) bodies.forEach( ( e ) => this.drawOne( ctx , e , s , lw , false ) );
  },

  drawOne( ctx , e , s , lw , dashed ) {
    const x = e.cx - 0.5;
    const y = e.cy - 0.5;
    ctx.save();
    ctx.strokeStyle = SOMA_ELLIPSE;
    ctx.lineWidth = lw;
    if ( dashed ) ctx.setLineDash( [ 4 / s , 3 / s ] );
    ctx.beginPath();
    ctx.ellipse( x , y , e.a , e.b , e.angle_deg * Math.PI / 180 , 0 , 2 * Math.PI );
    ctx.stroke();
    ctx.setLineDash( [] );
    const size = 3 / s;
    ctx.beginPath();
    ctx.moveTo( x - size , y ); ctx.lineTo( x + size , y );
    ctx.moveTo( x , y - size ); ctx.lineTo( x , y + size );
    ctx.stroke();
    ctx.restore();
  },
};
