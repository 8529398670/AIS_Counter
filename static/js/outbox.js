// Edits on their way to the server, kept on this computer until they arrive.
//
// Accepting, editing or deleting an AIS, recording a line, measuring a soma or
// marking an image done all show on screen at once and land here. They go to
// the server one at a time, in the order they were made. If the server is
// down or the connection drops, they wait (in localStorage, so a reload or a
// sign-in in between keeps them) and go once it answers again.
//
// Two things on the server make sending again safe: a create carries the
// browser's own client_id, so a second copy finds the first; and an edit
// carries the rev it was made from (expect), so one queued while someone else
// changed the row is refused (409) instead of overwriting their work.
//
// Each tab drains its own queue, so its edits keep their order. A queue left
// by a tab that closed or reloaded is taken over by the next one to look.
const Outbox = {
  user: null,
  tab: null,
  items: [],      // { seq, kind, bucket, key, path, body, label, done? }
  ids: {},        // bucket:key -> server id
  revs: {},       // bucket:key -> the rev the next edit is made from
  seq: 0,
  sending: false,
  inFlight: null, // the item being sent now
  waiting: false, // the last send failed for want of the server
  timer: null,
  delay: 0,
  handlers: {},   // bucket -> { reply( item , out ) , dropped( item , error ) }
  beatEvery: 5000,
  staleAfter: 20000,

  init( me ) {
    if ( !me || !me.id ) return;
    this.user = me.id;
    this.tab = this.newId();
    this.save();
    this.adopt();
    window.addEventListener( "online" , () => this.kick() );
    window.addEventListener( "storage" , ( e ) => { if ( e.key && e.key.startsWith( this.prefix() ) ) this.render(); } );
    document.addEventListener( "visibilitychange" , () => { if ( !document.hidden ) { this.adopt(); this.kick(); } } );
    // Closing or reloading: say so, so the next tab takes the queue over at once.
    window.addEventListener( "pagehide" , ( e ) => { if ( !e.persisted ) this.save( 0 ); } );
    // Back from the browser's back/forward cache: if another tab took this
    // queue over meanwhile, it is theirs to send now.
    window.addEventListener( "pageshow" , ( e ) => {
      if ( !e.persisted ) return;
      let mine = null;
      try { mine = window.localStorage.getItem( this.storageKey() ); } catch ( error ) { mine = "kept"; }
      if ( !mine && !this.sending ) { this.items = []; this.ids = {}; this.revs = {}; }
      this.save();
      this.kick();
    } );
    window.setInterval( () => { this.save(); this.adopt(); } , this.beatEvery );
    this.kick();
  },

  // A random id that works without a secure context (plain http on a LAN has
  // no crypto.randomUUID).
  newId() {
    const bytes = new Uint8Array( 16 );
    window.crypto.getRandomValues( bytes );
    const hex = Array.from( bytes , ( b ) => b.toString( 16 ).padStart( 2 , "0" ) ).join( "" );
    return hex.slice( 0 , 8 ) + "-" + hex.slice( 8 , 12 ) + "-" + hex.slice( 12 , 16 ) + "-" + hex.slice( 16 , 20 ) + "-" + hex.slice( 20 );
  },

  prefix() { return "ais.outbox." + this.user + "."; },
  storageKey() { return this.prefix() + this.tab; },
  mapKey( bucket , key ) { return bucket + ":" + key; },

  // This tab's queue as it is, with a heartbeat (beat 0: the tab has gone).
  save( beat ) {
    if ( !this.user ) return;
    try {
      if ( !this.items.length && beat !== 0 ) {
        window.localStorage.removeItem( this.storageKey() );
      } else {
        window.localStorage.setItem( this.storageKey() , JSON.stringify( {
          beat: beat === 0 ? 0 : Date.now() , seq: this.seq , items: this.items , ids: this.ids , revs: this.revs ,
        } ) );
      }
    } catch ( error ) { /* storage blocked or full: the queue lives only in this page */ }
    this.render();
  },

  // Queues no tab is beating for any more become this tab's, at the front:
  // they were made before anything this tab has queued since it opened.
  adopt() {
    const take = () => {
      let taken = false;
      try {
        for ( let i = window.localStorage.length - 1 ; i >= 0 ; i-- ) {
          const name = window.localStorage.key( i );
          if ( !name || !name.startsWith( this.prefix() ) || name === this.storageKey() ) continue;
          let other = null;
          try { other = JSON.parse( window.localStorage.getItem( name ) ); } catch ( error ) { other = null; }
          if ( other && Date.now() - ( other.beat || 0 ) < this.staleAfter ) continue;
          window.localStorage.removeItem( name );
          if ( !other || !Array.isArray( other.items ) ) continue;
          const theirs = other.items.filter( ( item ) => !item.done ).map( ( item ) => Object.assign( item , { seq: ++this.seq } ) );
          this.items = theirs.concat( this.items );
          Object.assign( this.ids , other.ids || {} );
          Object.keys( other.revs || {} ).forEach( ( k ) => { if ( !( k in this.revs ) ) this.revs[ k ] = other.revs[ k ]; } );
          taken = taken || theirs.length > 0;
        }
      } catch ( error ) { return; }
      if ( taken ) { this.save(); this.kick(); }
    };
    // Two tabs taking the same queue would send it twice: one at a time.
    if ( navigator.locks && navigator.locks.request ) navigator.locks.request( "ais-outbox-adopt" , take ).catch( () => {} );
    else take();
  },

  // Every queue of this person's, across tabs, for the badge.
  pendingCount() {
    let count = 0;
    try {
      for ( let i = 0 ; i < window.localStorage.length ; i++ ) {
        const name = window.localStorage.key( i );
        if ( !name || !name.startsWith( this.prefix() ) || name === this.storageKey() ) continue;
        const other = JSON.parse( window.localStorage.getItem( name ) || "{}" );
        count += ( other.items || [] ).length;
      }
    } catch ( error ) { /* storage blocked */ }
    return count + this.items.length;
  },

  pending() { return this.items.length > 0; },

  // Queue one edit. kind: create | update | delete | done. A create's key is
  // its client_id; anything else's is the row's key, with seed { id, rev }
  // from the row as this page has it (used when the queue knows it not yet).
  // path holds {id} where the server id goes. Returns the item.
  add( item , seed ) {
    const mk = this.mapKey( item.bucket , item.key );
    if ( seed && seed.id != null && !( mk in this.ids ) ) this.ids[ mk ] = seed.id;
    if ( seed && !( mk in this.revs ) ) this.revs[ mk ] = seed.rev || 0;
    // An update straight after an update of the same row, not yet sent: the
    // newer one is all that needs to go (arrow keys, a drag).
    const last = this.items[ this.items.length - 1 ];
    if ( last && last !== this.inFlight && item.kind === "update" && last.kind === "update" && last.bucket === item.bucket &&
         last.key === item.key && last.path === item.path ) {
      last.body = item.body;
      this.save();
      return last;
    }
    if ( item.kind === "done" ) {
      this.items = this.items.filter( ( other ) => other.kind !== "done" || other.key !== item.key || other === this.inFlight );
    }
    item.seq = ++this.seq;
    this.items.push( item );
    this.save();
    this.kick();
    return item;
  },

  // Try now (a new edit, the connection back, the tab looked at again).
  kick() {
    window.clearTimeout( this.timer );
    this.timer = null;
    this.delay = 0;
    this.drain();
  },

  later( ms ) {
    window.clearTimeout( this.timer );
    this.timer = window.setTimeout( () => { this.timer = null; this.drain(); } , ms );
  },

  async drain() {
    if ( this.sending || !this.user ) return;
    this.sending = true;
    try {
      while ( this.items.length ) {
        const item = this.items[ 0 ];
        this.inFlight = item;
        const result = await this.sendOne( item );
        this.inFlight = null;
        if ( result === "wait" ) return;
        // By reference: a queue taken over meanwhile went in at the front.
        const at = this.items.indexOf( item );
        if ( at >= 0 ) this.items.splice( at , 1 );
        this.waiting = false;
        this.delay = 0;
        if ( !this.items.length ) { this.ids = {}; this.revs = {}; }
        this.save();
      }
      this.drained();
    } finally {
      this.inFlight = null;
      this.sending = false;
      this.render();
    }
  },

  // "sent", "dropped" or "wait" (the server could not be reached: try later).
  async sendOne( item , retried ) {
    const mk = this.mapKey( item.bucket , item.key );
    let path = item.path;
    const body = Object.assign( {} , item.body );
    if ( path.includes( "{id}" ) ) {
      const id = this.ids[ mk ];
      // Its create never made it (refused): nothing on the server to change.
      if ( id == null ) return this.drop( item , new Error( I18n.get( "outbox.gone" ) || "That row was never saved." ) );
      path = path.replace( "{id}" , String( id ) );
    }
    if ( item.kind === "update" || item.kind === "delete" ) body.expect = this.revs[ mk ] || 0;
    let out;
    try {
      out = await Api.post( path , body );
    } catch ( error ) {
      if ( this.unreachable( error ) ) {
        this.waiting = true;
        this.delay = Math.min( 30000 , this.delay ? this.delay * 2 : 1000 );
        const after = Number( error.retryAfter ) * 1000;
        this.later( after > this.delay ? after : this.delay );
        this.render();
        return "wait";
      }
      if ( error.status === 401 ) return "wait"; // Api.request is taking the page to sign-in; the queue is kept
      if ( error.status === 403 && /csrf/i.test( error.message ) && !retried ) {
        try { await Api.me(); } catch ( refresh ) { return "wait"; }
        return this.sendOne( item , true );
      }
      if ( error.status === 404 && item.kind === "delete" ) return this.sent( item , mk , { ok: true , renumbered: [] } );
      return this.drop( item , error );
    }
    return this.sent( item , mk , out );
  },

  unreachable( error ) {
    return Boolean( error.network ) || error.status >= 500 || error.status === 429;
  },

  sent( item , mk , out ) {
    if ( out && out.id != null && item.kind !== "done" ) this.ids[ mk ] = out.id;
    if ( out && out.rev != null ) this.revs[ mk ] = out.rev;
    else if ( item.kind === "create" ) this.revs[ mk ] = 0;
    const handler = this.handlers[ item.bucket ];
    if ( handler && handler.reply ) {
      try { handler.reply( item , out ); } catch ( error ) { console.error( error ); }
    }
    return "sent";
  },

  // Refused for good (someone else changed it, it is gone, not allowed): said,
  // and the page puts back what the server has once nothing else is queued.
  drop( item , error ) {
    const conflict = error.status === 409;
    const text = ( conflict ? I18n.get( "outbox.conflict" ) : I18n.get( "outbox.dropped" ) ) || "Not saved: {what}";
    App.showError( text.replace( "{what}" , item.label || item.kind ) + ( conflict ? "" : " (" + error.message + ")" ) );
    this.resync = true;
    const handler = this.handlers[ item.bucket ];
    if ( handler && handler.dropped ) {
      try { handler.dropped( item , error ); } catch ( failure ) { console.error( failure ); }
    }
    return "dropped";
  },

  drained() {
    if ( !this.resync ) return;
    this.resync = false;
    Object.values( this.handlers ).forEach( ( handler ) => { if ( handler.resync ) handler.resync(); } );
  },

  // Resolves once this tab has nothing queued, or after ms (still offline).
  settled( ms ) {
    if ( !this.items.length ) return Promise.resolve( true );
    return new Promise( ( resolve ) => {
      const started = Date.now();
      const look = () => {
        if ( !this.items.length ) return resolve( true );
        if ( Date.now() - started >= ms ) return resolve( false );
        window.setTimeout( look , 200 );
      };
      look();
    } );
  },

  render() {
    const badge = document.getElementById( "ais-outbox" );
    if ( !badge ) return;
    const count = this.pendingCount();
    const text = this.waiting ? I18n.get( "outbox.offline" ) : I18n.get( "outbox.pending" );
    Dom.text( badge , ( text || "{n} edits pending" ).replace( "{n}" , count ) );
    badge.classList.toggle( "ais-outbox-offline" , this.waiting );
    Dom.show( badge , count > 0 );
  },
};

// Leaving with edits that never reached the server: they are kept here, but
// say so, as they are on no other computer until this one is back.
window.addEventListener( "beforeunload" , ( e ) => {
  if ( Outbox.pending() && Outbox.waiting ) {
    e.preventDefault();
    e.returnValue = "";
  }
} );
