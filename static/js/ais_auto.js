// Auto mode on the Process screen: every AIS on every image of the open
// batch, found without clicking, with the method and settings the Settings
// screen has. Settings > Auto mode says how they are checked:
//
// - each: stop on every image with its candidates drawn and ticked, each
//   numbered as it will be saved. Clicking one unticks it (any other click
//   traces by hand, as always); Enter saves the ticked ones and marks the
//   image done, N leaves the image as it was.
// - end:  save every candidate as it is found, then go back over the images
//   to delete wrong ones and add missed ones; Enter marks the image done
//   (reviewed). Review resumes this later for images with auto AIS not
//   marked done.
// - all:  save every candidate, no stops.
//
// The Edit and Delete tools (ais.js) act on the candidates as on saved AIS.
// Candidates shorter, dimmer or thinner than Settings > Auto mode allows are
// left out (the server reports each one's shape: app/analysis/service.shape).
// While confirming, the panel has those filters and the start end too: a
// filter change re-sorts the image's candidates at once, a start change finds
// them again.
//
// The finding is the server's (POST /api/ais/detect, app/analysis/detect.py):
// each candidate is exactly what a click at its seed gives, so a saved one
// carries that click like any other row, plus origin "auto". An image takes
// some seconds, so the next one is always being worked on while the current
// one is shown.
const AisAuto = {
  // { mode: each | end | all | review, queue: [image indexes], at, step,
  //   pending: Map index -> Promise, found, hidden, saved, deleted, errors, params }
  run: null,
  phase: null,      // "finding" | "confirm" | "review"
  candidates: [],   // confirm: [{ result, on }] for the image queue[at], those the filters keep
  pool: [],         // confirm: every candidate found there, filtered or not
  error: "",        // confirm: why that image found nothing
  busy: false,

  init() {
    Dom.get( "ais-auto-start" ).addEventListener( "click" , () => this.start() );
    Dom.get( "ais-auto-review" ).addEventListener( "click" , () => this.startReview() );
    Dom.get( "ais-auto-stop" ).addEventListener( "click" , () => this.stop() );
    Dom.get( "ais-auto-next" ).addEventListener( "click" , () => this.next() );
    Dom.get( "ais-auto-skip" ).addEventListener( "click" , () => this.skip() );
    Object.entries( this.quick ).forEach( ( [ id , field ] ) => {
      Dom.get( id ).addEventListener( "change" , ( e ) => this.setQuick( field , e.target ) );
    } );
  },

  // The panel's quick settings: control id -> Settings field.
  quick: { "ais-auto-quick-start": "auto_start" , "ais-auto-quick-length": "auto_min_length" ,
    "ais-auto-quick-brightness": "auto_min_brightness" , "ais-auto-quick-width": "auto_min_width" },

  // The Auto and Review buttons follow the batch and its progress, and so
  // does the panel (a hand-traced AIS added moves the candidates' numbers up,
  // and joins the saved ones under review).
  refresh() {
    if ( this.phase === "confirm" || this.phase === "review" ) this.render();
    const ready = Boolean( Ais.batch && Ais.included().length );
    Dom.get( "ais-auto-start" ).disabled = !ready || Boolean( this.run );
    const left = ready ? this.unreviewed() : [];
    Dom.show( Dom.get( "ais-auto-review" ) , !this.run && left.length > 0 );
    Dom.text( Dom.get( "ais-auto-review-count" ) , String( left.length ) );
  },

  // Included images with auto AIS on them that are not marked done.
  unreviewed() {
    return Ais.included().filter( ( i ) => {
      const entry = Ais.images[ i ];
      return !Ais.isMarkedDone( entry ) && Ais.savedRows( entry ).some( ( row ) => row.origin === "auto" );
    } );
  },

  current() {
    return this.run ? this.run.queue[ this.run.at ] : -1;
  },

  // --- running -------------------------------------------------------------------

  start() {
    if ( !Ais.batch || this.run ) return;
    const skip = Settings.autoSkipDone();
    const queue = Ais.included().filter( ( i ) => !( skip && Ais.isComplete( Ais.images[ i ] ) ) );
    if ( !queue.length ) {
      Ais.status( I18n.get( "ais.auto_nothing" ) );
      return;
    }
    Ais.reject();
    // The settings as they are now, for the whole run (the panel's quick
    // settings change the start and filters).
    const params = Object.assign( {
      threshold: Settings.threshold(),
      settings: Settings.methodSettings(),
    } , this.filters() );
    this.run = { mode: Settings.autoReview() , queue: queue , at: 0 , step: 0 , pending: new Map() ,
      found: 0 , hidden: 0 , saved: 0 , deleted: 0 , errors: 0 , params: params };
    this.refresh();
    if ( this.run.mode === "each" ) this.confirmAt();
    else this.saveAll();
  },

  // Review button: clean up auto AIS saved earlier.
  startReview() {
    if ( !Ais.batch || this.run ) return;
    const queue = this.unreviewed();
    if ( !queue.length ) return;
    Ais.reject();
    this.run = { mode: "review" , queue: queue , at: 0 , step: 0 , pending: new Map() ,
      found: 0 , hidden: 0 , saved: 0 , deleted: 0 , errors: 0 , params: null };
    this.refresh();
    this.reviewAt();
  },

  // Settings > Auto mode's start end and filters, as a run uses them.
  filters() {
    return {
      start: Settings.autoStart(),
      min: Math.max( Settings.minLength() || 0 , Settings.autoMinLength() || 0 ),
      brightness: ( Settings.autoMinBrightness() || 0 ) / 100,
      width: Settings.autoMinWidth() || 0,
    };
  },

  // A quick setting changed on the panel: kept in Settings too, then the
  // current image's candidates follow it.
  setQuick( field , control ) {
    const run = this.run;
    const kept = Settings.setGeneral( field , control.value );
    control.value = kept;
    if ( !run || run.mode !== "each" ) return;
    const start = run.params.start;
    Object.assign( run.params , this.filters() );
    if ( run.params.start !== start ) {
      // Traced from another end: find them all again.
      run.pending.clear();
      if ( this.phase === "confirm" ) {
        run.found -= this.candidates.length;   // this image's count is redone
        run.hidden -= this.pool.length - this.candidates.length;
      }
      if ( this.phase === "confirm" || this.phase === "finding" ) this.confirmAt();
    } else if ( this.phase === "confirm" ) {
      this.refilter();
    }
  },

  // The pool through the filters again; unticks and edits stay.
  refilter() {
    const run = this.run;
    const kept = this.pool.filter( ( c ) => this.passes( c.result , run.params ) );
    run.found += kept.length - this.candidates.length;
    run.hidden += this.candidates.length - kept.length;
    this.candidates = kept;
    this.render();
    Ais.draw();
  },

  // A found image's candidates the filters keep, and how many they leave out.
  filtered( out , params ) {
    const kept = out.candidates.filter( ( c ) => this.passes( c , params ) );
    return { candidates: kept , hidden: out.candidates.length - kept.length };
  },

  // The image's candidates (a promise), asked for once per run (again after
  // the start end changes), all of them: filtered() picks.
  find( index ) {
    const run = this.run;
    if ( !run.pending.has( index ) ) {
      const entry = Ais.images[ index ];
      const p = ( async () => {
        await Ais.upload( entry );
        const out = await Api.post( "/api/ais/detect" , {
          processed: Ais.sha( entry ),
          raw: Ais.kind( entry ) === "pair" ? Ais.sha( entry , "raw" ) : null,
          threshold: run.params.threshold,
          settings: run.params.settings,
          start: run.params.start,
          exclude: Ais.savedRows( entry ).map( ( row ) => row.pixels ),
        } );
        out.candidates = out.candidates.map( ( c ) => Object.assign( c , { image: entry.key , source: Ais.kind( entry ) } ) );
        return out;
      } )();
      p.catch( () => {} );   // awaited (and reported) when its turn comes
      run.pending.set( index , p );
    }
    return run.pending.get( index );
  },

  // Settings > Auto mode's filters: long, bright and wide enough.
  passes( c , params ) {
    const m = c.measures;
    const shape = c.shape || {};
    if ( params.min && m.length_um < params.min ) return false;
    if ( params.brightness && shape.brightness < params.brightness ) return false;
    if ( params.width && shape.width_um < params.width ) return false;
    return true;
  },

  // Start on the next image too, so it is ready sooner.
  ahead() {
    const run = this.run;
    if ( run.at + 1 < run.queue.length ) this.find( run.queue[ run.at + 1 ] );
  },

  // each: find the current image's candidates, then wait for Enter or N.
  async confirmAt() {
    const run = this.run;
    if ( run.at >= run.queue.length ) {
      this.finish();
      return;
    }
    const step = ++run.step;
    const index = run.queue[ run.at ];
    this.phase = "finding";
    this.candidates = [];
    this.pool = [];
    this.error = "";
    this.render();
    if ( Ais.index !== index ) Ais.show( index );
    const found = this.find( index );
    this.ahead();
    let out = { candidates: [] };
    try {
      out = await found;
    } catch ( error ) {
      this.error = error.message;
      run.errors += 1;
    }
    if ( this.run !== run || run.step !== step ) return;
    this.phase = "confirm";
    this.pool = out.candidates.map( ( result ) => ( { result: result , on: true } ) );
    this.candidates = this.pool.filter( ( c ) => this.passes( c.result , run.params ) );
    run.found += this.candidates.length;
    run.hidden += this.pool.length - this.candidates.length;
    this.render();
    Ais.draw();
  },

  // end / all: save everything found, image after image.
  async saveAll() {
    const run = this.run;
    this.phase = "finding";
    while ( this.run === run && run.at < run.queue.length ) {
      const index = run.queue[ run.at ];
      const entry = Ais.images[ index ];
      this.render();
      if ( Ais.index !== index ) Ais.show( index );
      const found = this.find( index );
      this.ahead();
      try {
        const out = this.filtered( await found , run.params );
        if ( this.run !== run ) return;
        run.found += out.candidates.length;
        run.hidden += out.hidden;
        for ( const c of out.candidates ) {
          await Ais.saveRow( entry , Ais.rowFor( entry , c , "auto" ) );
          run.saved += 1;
        }
      } catch ( error ) {
        if ( this.run !== run ) return;
        run.errors += 1;
        App.showError( entry.key + ": " + error.message );
      }
      run.at += 1;
      Ais.renderTable();
      Ais.renderPicker();
      Ais.draw();
    }
    if ( this.run !== run ) return;
    if ( run.mode === "end" ) {
      run.at = 0;
      run.reviewing = true;
      this.reviewAt();
    } else {
      this.finish();
    }
  },

  // end, then Review: show the current image's saved AIS for cleanup.
  reviewAt() {
    const run = this.run;
    if ( run.at >= run.queue.length ) {
      this.finish();
      return;
    }
    run.step += 1;
    this.phase = "review";
    const index = run.queue[ run.at ];
    if ( Ais.index !== index ) Ais.show( index );
    this.render();
    Ais.draw();
  },

  // Enter, or the panel's main button.
  async next() {
    const run = this.run;
    if ( !run || this.busy || this.phase === "finding" ) return;
    // A hand trace or an edit is waiting: this keeps it, like Enter.
    if ( Ais.pending() ) {
      Ais.accept();
      return;
    }
    const index = this.current();
    const entry = Ais.images[ index ];
    // Looking at another image: go back to the one being checked first.
    if ( Ais.index !== index ) {
      Ais.show( index );
      return;
    }
    this.busy = true;
    try {
      if ( this.phase === "confirm" ) {
        for ( const c of this.candidates.filter( ( x ) => x.on ) ) {
          await Ais.saveRow( entry , Ais.rowFor( entry , c.result , "auto" ) );
          run.saved += 1;
          this.candidates = this.candidates.filter( ( x ) => x !== c );   // never saved twice
          this.pool = this.pool.filter( ( x ) => x !== c );
        }
      }
      await Ais.markDone( entry );
    } catch ( error ) {
      App.showError( error.message );
      return;
    } finally {
      this.busy = false;
      Ais.renderTable();
      Ais.renderPicker();
      Ais.draw();
    }
    if ( this.run !== run ) return;
    run.at += 1;
    if ( this.phase === "confirm" ) this.confirmAt();
    else this.reviewAt();
  },

  // N, or Skip: on to the next image, leaving this one as it is.
  skip() {
    const run = this.run;
    if ( !run || this.busy ) return;
    if ( run.mode !== "each" && this.phase !== "review" ) return;   // saving runs on its own
    run.at += 1;
    if ( this.phase === "review" ) this.reviewAt();
    else this.confirmAt();
  },

  // --- the candidates, for the Edit and Delete tools --------------------------

  // The candidates drawn on the image on screen (none outside confirm).
  shownCandidates() {
    return this.run && this.phase === "confirm" && Ais.index === this.current() ? this.candidates : [];
  },

  removeCandidate( c ) {
    this.candidates = this.candidates.filter( ( x ) => x !== c );
    this.pool = this.pool.filter( ( x ) => x !== c );
    this.render();
    Ais.draw();
  },

  // An edited candidate: its new trace, ticked.
  replaceCandidate( c , result ) {
    c.result = result;
    c.on = true;
    this.render();
    Ais.draw();
  },

  // The number each ticked candidate will be saved under: after the image's
  // saved AIS, in list order. Map candidate -> n.
  numbers() {
    const entry = Ais.images[ this.current() ];
    let n = entry ? Ais.savedRows( entry ).reduce( ( top , row ) => Math.max( top , row.n ) , 0 ) : 0;
    const out = new Map();
    this.candidates.forEach( ( c ) => { if ( c.on ) out.set( c , ++n ); } );
    return out;
  },

  // A saved row was deleted while this run is on (Delete tool, review list).
  rowDeleted() {
    if ( this.run ) this.run.deleted += 1;
    this.render();
  },

  // Esc, or Stop. Anything already saved stays.
  stop() {
    const run = this.run;
    if ( !run ) return;
    this.finish( true );
  },

  // Forget a run without a word (another batch was opened).
  reset() {
    this.run = null;
    this.phase = null;
    this.candidates = [];
    this.pool = [];
    this.render();
  },

  finish( stopped ) {
    const run = this.run;
    this.reset();
    this.refresh();
    Ais.draw();
    if ( !run ) return;
    const images = Math.min( run.at , run.queue.length );
    let text;
    if ( run.mode === "review" ) {
      text = I18n.get( "ais.auto_review_done" ).replace( "{images}" , images ).replace( "{deleted}" , run.deleted );
    } else {
      text = I18n.get( stopped ? "ais.auto_stopped" : "ais.auto_done" )
        .replace( "{saved}" , run.saved ).replace( "{found}" , run.found ).replace( "{hidden}" , run.hidden )
        .replace( "{images}" , run.reviewing ? run.queue.length : images ).replace( "{total}" , run.queue.length );
      if ( run.deleted ) text += " " + I18n.get( "ais.auto_deleted" ).replace( "{deleted}" , run.deleted );
    }
    if ( run.errors ) text += " " + I18n.get( "ais.auto_errors" ).replace( "{errors}" , run.errors );
    Ais.status( text , true );
  },

  // --- the panel and the canvas ----------------------------------------------

  render() {
    const run = this.run;
    Dom.show( Dom.get( "ais-auto-panel" ) , Boolean( run ) );
    if ( !run ) return;
    const total = run.queue.length;
    const k = Math.min( run.at + 1 , total );
    const reviewing = this.phase === "review";
    Dom.text( Dom.get( "ais-auto-progress" ) , ( reviewing
      ? I18n.get( "ais.auto_progress_review" )
      : I18n.get( "ais.auto_progress" ).replace( "{found}" , run.found ).replace( "{saved}" , run.saved )
        .replace( "{hidden}" , run.hidden )
    ).replace( "{k}" , k ).replace( "{n}" , total ) );
    Dom.show( Dom.get( "ais-auto-busy" ) , this.phase === "finding" );
    Dom.text( Dom.get( "ais-auto-busy-text" ) , I18n.get( run.mode === "each" ? "ais.auto_finding" : "ais.auto_saving" ) );
    Dom.text( Dom.get( "ais-auto-help" ) , reviewing ? I18n.get( "ais.auto_help_review" ) : "" );
    Dom.show( Dom.get( "ais-auto-help" ) , reviewing );
    const quick = run.mode === "each" && ( this.phase === "confirm" || this.phase === "finding" );
    Dom.show( Dom.get( "ais-auto-quick" ) , quick );
    if ( quick ) {
      Object.entries( this.quick ).forEach( ( [ id , field ] ) => {
        const control = Dom.get( id );
        if ( document.activeElement !== control ) control.value = Settings.values[ field ];
      } );
    }
    Dom.show( Dom.get( "ais-auto-actions" ) , this.phase === "confirm" || reviewing );
    const ticked = this.candidates.filter( ( c ) => c.on ).length;
    Dom.text( Dom.get( "ais-auto-next-text" ) , this.phase === "confirm"
      ? I18n.get( ticked ? "ais.auto_save_next" : "ais.auto_none_next" ).replace( "{n}" , ticked )
      : I18n.get( "ais.auto_review_next" ) );
    const list = Dom.get( "ais-auto-list" );
    Dom.clear( list );
    if ( this.phase === "confirm" ) this.renderCandidates( list );
    if ( reviewing ) this.renderRows( list );
  },

  renderCandidates( list ) {
    if ( this.error ) list.appendChild( Dom.el( "li" , { class: "list-group-item px-0 text-danger" , text: this.error } ) );
    else if ( !this.candidates.length ) list.appendChild( Dom.el( "li" , { class: "list-group-item px-0 text-body-secondary" , text: I18n.get( "ais.auto_none" ) } ) );
    const numbers = this.numbers();
    this.candidates.forEach( ( c ) => {
      const box = Dom.el( "input" , { class: "form-check-input me-2" , attrs: { type: "checkbox" } } );
      box.checked = c.on;
      box.addEventListener( "change" , () => {
        c.on = box.checked;
        this.render();
        Ais.draw();
      } );
      const m = c.result.measures;
      list.appendChild( Dom.el( "li" , { class: "list-group-item px-0" , children: [
        Dom.el( "label" , { class: "d-flex align-items-center w-100 gap-2" , children: [
          box,
          Dom.el( "span" , { class: "ais-auto-n" , text: numbers.has( c ) ? "#" + numbers.get( c ) : "–" } ),
          Dom.el( "span" , { class: "me-auto text-body-secondary" , text: this.shapeText( c.result.shape ) } ),
          Dom.el( "span" , { class: "fw-semibold" , text: m.length_str + " µm" } ),
        ] } ),
      ] ,
      on: { mouseenter: () => this.highlight( "candidate" , c , c.result.pixels ) , mouseleave: () => this.highlight() } } ) );
    } );
  },

  // "2.9 µm · 62 %": width and brightness, what the filters look at.
  shapeText( shape ) {
    if ( !shape ) return "";
    return Ais.fmt( Number( shape.width_um.toFixed( 1 ) ) ) + " µm · " + Math.round( shape.brightness * 100 ) + " %";
  },

  // Hovering a list entry highlights its trace on the image.
  highlight( kind , item , pixels ) {
    Ais.hover = item ? { kind: kind , item: item , pixels: pixels } : null;
    Ais.draw();
  },

  renderRows( list ) {
    const entry = Ais.images[ this.current() ];
    const rows = entry ? Ais.savedRows( entry ) : [];
    if ( !rows.length ) list.appendChild( Dom.el( "li" , { class: "list-group-item px-0 text-body-secondary" , text: I18n.get( "ais.auto_none_saved" ) } ) );
    rows.forEach( ( row ) => {
      const del = Dom.el( "button" , {
        class: "btn btn-sm btn-link text-danger p-0 ms-2",
        attrs: { type: "button" , title: I18n.get( "ais.auto_delete" ) , "aria-label": I18n.get( "ais.auto_delete" ) },
        children: [ Dom.el( "i" , { class: "bi bi-trash" } ) ],
        on: { click: () => { this.highlight(); Ais.deleteRow( row ); } },
      } );
      const children = [ Dom.el( "span" , { class: "ais-auto-n" , text: "#" + row.n } ) ];
      if ( row.origin === "auto" ) children.push( Dom.badge( I18n.get( "ais.auto_origin" ) ) );
      children.push( Dom.el( "span" , { class: "me-auto text-body-secondary" , text: row.width_um != null ? this.shapeText( { width_um: row.width_um , brightness: row.brightness } ) : "" } ) );
      children.push( Dom.el( "span" , { class: "fw-semibold" , text: row.length_str + " µm" } ) , del );
      list.appendChild( Dom.el( "li" , {
        class: "list-group-item px-1 d-flex align-items-center gap-2",
        children: children,
        on: { mouseenter: () => this.highlight( "row" , row , row.pixels ) , mouseleave: () => this.highlight() },
      } ) );
    } );
  },

  // Called from Ais.draw with the image transform set.
  draw( ctx , s , lw ) {
    if ( !this.run || Ais.index !== this.current() ) return;
    if ( this.phase === "confirm" ) {
      const numbers = this.numbers();
      ctx.font = ( 12 / s ) + "px sans-serif";
      this.candidates.forEach( ( c ) => {
        const colour = c.on ? "rgba(255, 60, 220, 1)" : "rgba(170, 170, 170, 0.7)";
        Ais.polyline( c.result.pixels , colour , lw );
        const p = c.result.pixels[ 0 ];
        if ( p && numbers.has( c ) ) {
          ctx.fillStyle = colour;
          ctx.fillText( "#" + numbers.get( c ) , p[ 0 ] + 3 / s , p[ 1 ] - 3 / s );
        }
      } );
    }
  },

  // A Trace-tool click while candidates are shown: one near a candidate
  // ticks or unticks it (true); anything else traces by hand as usual.
  onClick( point ) {
    if ( !this.shownCandidates().length || Ais.pending() ) return false;
    const target = Ais.nearestTrace( point );
    if ( !target || target.kind !== "candidate" ) return false;
    target.item.on = !target.item.on;
    this.render();
    Ais.draw();
    return true;
  },

  // Keys while a run is on: true when handled. A hand trace or an edit
  // waiting for Enter / N keeps those keys; Esc reaches here only when no
  // edit or Edit / Delete tool is on (ais.js).
  onKey( event ) {
    if ( !this.run ) return false;
    const key = event.key;
    if ( key === "Escape" ) {
      event.preventDefault();
      this.stop();
      return true;
    }
    if ( Ais.pending() ) return false;
    if ( key === "Enter" ) {
      event.preventDefault();
      this.next();
      return true;
    }
    if ( key === "n" || key === "N" ) {
      this.skip();
      return true;
    }
    return false;
  },
};
