// Treatments (admins, the Batches screen): what each image's culture was
// treated with, for the exports that group by it (static/js/compare.js,
// app/analysis/compare.py). The server guesses each from the image's original
// name ("BB50 DMSO+FK506 A-02" -> "DMSO+FK506"); this dialog shows the
// guesses next to what is saved, to be checked, corrected and saved
// (GET/POST /api/ais/batches/<id>/treatments). Only included images are
// listed: the others are in no export.
//
// Many at once: rows are ticked one by one (Shift-click ticks a run), a
// whole folder by its row, all by the header, or every name containing what
// is typed in the match box; Apply writes one treatment into every ticked row.
// The chips above the table are the groups the inputs make right now, with
// their counts, matched the way exports match them (ignoring case); a chip
// ticks its rows, so a group is renamed in two clicks.
//
// Two ways to guess, for the ticked rows (every row when none is): "as
// written" keeps each batch's own spelling, so "TM+KCl+WO" and "TM+KCl WO"
// stay two treatments; "matched" gives spellings that differ only in case,
// "+", spacing or hr/hrs/h one spelling across every batch here (one saved
// already, in any batch, first), so they become one. The admin picks per
// batch by ticking its folder rows first.
const Treatments = {
  modal: null,
  list: [],          // the batches the dialog is for
  rows: [],          // [{ batch, key, folder, guess, written, guessKey, input, box, saved }]
  last: null,        // the row ticked last, for Shift-click runs
  resolve: null,     // review()'s promise: true once saved, false when closed
  saving: false,

  init() {
    const element = Dom.get( "treatments-modal" );
    this.modal = bootstrap.Modal.getOrCreateInstance( element );
    element.addEventListener( "hidden.bs.modal" , () => this.finish( false ) );
    Dom.get( "treatments-fill" ).addEventListener( "click" , () => this.fill() );
    Dom.get( "treatments-guess-written" ).addEventListener( "click" , () => this.guess( false ) );
    Dom.get( "treatments-guess-matched" ).addEventListener( "click" , () => this.guess( true ) );
    Dom.get( "treatments-clear" ).addEventListener( "click" , () => this.clear() );
    Dom.get( "treatments-save" ).addEventListener( "click" , () => this.save() );
    Dom.get( "treatments-all" ).addEventListener( "change" , ( e ) => this.tick( this.rows , e.target.checked ) );
    Dom.get( "treatments-match" ).addEventListener( "input" , ( e ) => this.match( e.target.value ) );
    Dom.get( "treatments-bulk-name" ).addEventListener( "input" , () => this.render() );
    Dom.get( "treatments-bulk-name" ).addEventListener( "keydown" , ( e ) => {
      if ( e.key === "Enter" ) { e.preventDefault(); this.apply(); }
    } );
    Dom.get( "treatments-apply" ).addEventListener( "click" , () => this.apply() );
  },

  // --- ticking many and applying one treatment ------------------------------

  tick( rows , on ) {
    rows.forEach( ( r ) => { r.box.checked = on; } );
    this.render();
  },

  // Every name containing the text ticked, the rest not; empty unticks all.
  match( text ) {
    const want = text.trim().toLowerCase();
    this.rows.forEach( ( r ) => { r.box.checked = Boolean( want ) && r.original.toLowerCase().includes( want ); } );
    this.render();
  },

  // A click on a row's box; with Shift, every row from the last one ticked
  // to this one takes its state.
  clicked( row , event ) {
    if ( event.shiftKey && this.last && this.last !== row ) {
      const [ a , b ] = [ this.rows.indexOf( this.last ) , this.rows.indexOf( row ) ].sort( ( x , y ) => x - y );
      this.rows.slice( a , b + 1 ).forEach( ( r ) => { r.box.checked = row.box.checked; } );
    }
    this.last = row;
    this.render();
  },

  apply() {
    const name = Dom.get( "treatments-bulk-name" ).value.trim();
    const ticked = this.rows.filter( ( r ) => r.box.checked );
    if ( !name || !ticked.length ) return;
    ticked.forEach( ( r ) => { r.input.value = name; r.box.checked = false; } );
    const known = Dom.get( "treatments-known" );
    if ( ![ ...known.options ].some( ( o ) => o.value === name ) ) known.appendChild( Dom.el( "option" , { attrs: { value: name } } ) );
    Dom.get( "treatments-match" ).value = "";
    Dom.get( "treatments-bulk-name" ).value = "";
    Dom.toast( I18n.get( "treatments.applied" ).replace( "{name}" , name ).replace( "{n}" , ticked.length ) , "ok" );
    this.render();
  },

  // Each batch's included images: [{ batch, rows }].
  async load( list ) {
    const all = await Promise.all( list.map( ( b ) => Api.request( "/api/ais/batches/" + b.id + "/treatments" ) ) );
    return list.map( ( b , i ) => ( { batch: b , rows: all[ i ].treatments.filter( ( r ) => r.included ) } ) );
  },

  // Before an export that groups by treatment. force (Compare): the dialog
  // opens while any image has none saved; otherwise (a batch report) only
  // while a batch has none saved at all but some are guessed, so a batch
  // already reviewed is not asked about again. Resolves false when the
  // dialog was closed without saving.
  async ensure( list , force ) {
    const loaded = await this.load( list );
    const missing = loaded.some( ( { rows } ) => rows.some( ( r ) => !r.treatment ) );
    const unreviewed = loaded.some( ( { rows } ) => !rows.some( ( r ) => r.treatment ) && rows.some( ( r ) => r.guess ) );
    if ( force ? !missing : !unreviewed ) return true;
    return this.open( loaded );
  },

  // From a batch's menu: always opens.
  async review( list ) {
    return this.open( await this.load( list ) );
  },

  open( loaded ) {
    this.list = loaded.map( ( item ) => item.batch );
    const known = new Set();
    loaded.forEach( ( { rows } ) => rows.forEach( ( r ) => { if ( r.treatment ) known.add( r.treatment ); if ( r.guess ) known.add( r.guess ); } ) );
    Dom.get( "treatments-known" ).replaceChildren( ...[ ...known ].sort().map( ( t ) => Dom.el( "option" , { attrs: { value: t } } ) ) );
    Dom.text( Dom.get( "treatments-batches" ) , this.list.map( ( b ) => b.name ).join( ", " ) );
    const multi = loaded.length > 1;
    this.rows = [];
    this.last = null;
    const body = [];
    // A heading row per folder once there is more than one, ticking its images.
    const folders = new Set( loaded.flatMap( ( { batch: b , rows } ) => rows.map( ( r ) => b.id + "\n" + r.folder ) ) );
    const columns = multi ? 4 : 3;
    loaded.forEach( ( { batch: b , rows } ) => {
      const byFolder = new Map();
      rows.forEach( ( r ) => {
        if ( !byFolder.has( r.folder ) ) byFolder.set( r.folder , [] );
        byFolder.get( r.folder ).push( r );
      } );
      byFolder.forEach( ( inFolder , folder ) => {
        const mine = [];
        if ( folders.size > 1 ) {
          const box = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" ,
            title: I18n.get( "treatments.select_folder" ) , "aria-label": I18n.get( "treatments.select_folder" ) + ": " + folder } } );
          box.addEventListener( "change" , () => this.tick( mine , box.checked ) );
          body.push( Dom.el( "tr" , { class: "treatments-group" , children: [
            Dom.el( "td" , { children: [ box ] } ),
            Dom.el( "td" , { attrs: { colspan: String( columns - 1 ) } ,
              text: ( multi ? b.name + " · " : "" ) + ( folder || b.name ) + " (" + inFolder.length + ")" } ),
          ] } ) );
        }
        inFolder.forEach( ( r ) => {
          const input = Dom.el( "input" , { class: "form-control form-control-sm" ,
            attrs: { type: "text" , maxlength: "100" , list: "treatments-known" , placeholder: r.guess || I18n.get( "treatments.none" ) ,
              "aria-label": I18n.get( "treatments.col_treatment" ) + ": " + r.original } } );
          input.value = r.treatment || r.guess || "";
          input.addEventListener( "input" , () => this.render() );
          const box = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , "aria-label": r.original } } );
          const row = { batch: b , key: r.key , original: r.original , folder: folder , guess: r.guess || "" , written: r.guess_written || "" , guessKey: r.guess_key || "" , input: input , box: box , saved: r.treatment || "" };
          box.addEventListener( "click" , ( event ) => this.clicked( row , event ) );
          this.rows.push( row );
          mine.push( row );
          body.push( Dom.el( "tr" , { children: [
            Dom.el( "td" , { children: [ box ] } ),
            ...( multi ? [ Dom.el( "td" , { class: "text-body-secondary text-nowrap" , text: b.name } ) ] : [] ),
            Dom.el( "td" , { class: "text-break" , text: r.original } ),
            Dom.el( "td" , { children: [ input ] } ),
          ] } ) );
        } );
      } );
    } );
    Dom.get( "treatments-match" ).value = "";
    Dom.get( "treatments-bulk-name" ).value = "";
    // Names blinded before they got here, with no __Translation.txt: nothing to guess from.
    Dom.show( Dom.get( "treatments-blind" ) , this.rows.length > 0 && this.rows.every( ( r ) => /^\d{1,5}-\d{1,5}-\d{1,5}/.test( r.original ) ) );
    Dom.show( Dom.get( "treatments-col-batch" ) , multi );
    Dom.get( "treatments-rows" ).replaceChildren( ...body );
    Dom.show( Dom.get( "treatments-empty" ) , !this.rows.length );
    this.render();
    this.modal.show();
    return new Promise( ( resolve ) => { this.resolve = resolve; } );
  },

  render() {
    const blank = this.rows.filter( ( r ) => !r.input.value.trim() ).length;
    Dom.text( Dom.get( "treatments-status" ) , blank ? I18n.get( "treatments.blank" ).replace( "{n}" , blank ) : "" );
    Dom.get( "treatments-save" ).disabled = this.saving || !this.rows.length;
    const ticked = this.rows.filter( ( r ) => r.box.checked ).length;
    Dom.text( Dom.get( "treatments-picked" ) , I18n.get( "treatments.picked" ).replace( "{n}" , ticked ) );
    Dom.get( "treatments-apply" ).disabled = !ticked || !Dom.get( "treatments-bulk-name" ).value.trim();
    const all = Dom.get( "treatments-all" );
    all.checked = ticked > 0 && ticked === this.rows.length;
    all.indeterminate = ticked > 0 && ticked < this.rows.length;
    this.groups();
  },

  // One chip per treatment in the inputs, ignoring case as the exports do
  // (blank as "none"), named the way most of its rows spell it, most images
  // first; a click ticks exactly those rows.
  groups() {
    const by = new Map();
    this.rows.forEach( ( r ) => {
      const key = r.input.value.trim().toLowerCase();
      if ( !by.has( key ) ) by.set( key , [] );
      by.get( key ).push( r );
    } );
    const named = [ ...by.values() ].map( ( rows ) => [ this.common( rows.map( ( r ) => r.input.value.trim() ) ) , rows ] );
    const chips = named.sort( ( a , b ) => b[ 1 ].length - a[ 1 ].length || a[ 0 ].localeCompare( b[ 0 ] ) ).map( ( [ name , rows ] ) => {
      const chip = Dom.el( "button" , { class: "btn btn-sm " + ( name ? "btn-outline-secondary" : "btn-outline-warning" ) ,
        attrs: { type: "button" , title: I18n.get( "treatments.group_tick" ).replace( "{n}" , rows.length ) } ,
        text: ( name || I18n.get( "treatments.none" ) ) + " · " + rows.length } );
      chip.addEventListener( "click" , () => {
        this.rows.forEach( ( r ) => { r.box.checked = rows.includes( r ); } );
        this.render();
      } );
      return chip;
    } );
    const label = Dom.el( "span" , { class: "small text-body-secondary me-1" , text: I18n.get( "treatments.groups" ) } );
    Dom.get( "treatments-groups" ).replaceChildren( ...( chips.length ? [ label , ...chips ] : [] ) );
  },

  // Blank inputs take their guess (the placeholder).
  fill() {
    this.rows.forEach( ( r ) => { if ( !r.input.value.trim() && r.input.placeholder !== I18n.get( "treatments.none" ) ) r.input.value = r.input.placeholder; } );
    this.render();
  },

  // The spelling most of these have (the first met on a tie).
  common( names ) {
    const counts = new Map();
    names.forEach( ( n ) => counts.set( n , ( counts.get( n ) || 0 ) + 1 ) );
    return [ ...counts ].reduce( ( best , c ) => ( c[ 1 ] > best[ 1 ] ? c : best ) )[ 0 ];
  },

  // The ticked rows (every row when none is) take their guess, as written
  // or matched; a value saved or typed is only replaced after a confirm.
  // Rows without a guess keep what they have.
  guess( matched ) {
    const ticked = this.rows.filter( ( r ) => r.box.checked );
    const target = ticked.length ? ticked : this.rows;
    // Matched: one spelling per key across every batch in the dialog.
    const spelling = new Map();
    if ( matched ) {
      const byKey = new Map();
      this.rows.filter( ( r ) => r.guess ).forEach( ( r ) => {
        if ( !byKey.has( r.guessKey ) ) byKey.set( r.guessKey , [] );
        byKey.get( r.guessKey ).push( r.guess );
      } );
      byKey.forEach( ( names , key ) => spelling.set( key , this.common( names ) ) );
    }
    const pick = ( r ) => ( matched ? ( r.guess ? spelling.get( r.guessKey ) : "" ) : r.written );
    const changing = target.filter( ( r ) => pick( r ) && r.input.value.trim() !== pick( r ) );
    if ( !changing.length ) { Dom.toast( I18n.get( "treatments.guess_none" ) , "ok" ); return; }
    const overwriting = changing.filter( ( r ) => r.input.value.trim() ).length;
    if ( overwriting && !window.confirm( I18n.get( "treatments.guess_confirm" ).replace( "{n}" , overwriting ) ) ) return;
    changing.forEach( ( r ) => { r.input.value = pick( r ); } );
    ticked.forEach( ( r ) => { r.box.checked = false; } );
    Dom.toast( I18n.get( "treatments.guessed" ).replace( "{n}" , changing.length ) , "ok" );
    this.render();
  },

  // The ticked rows (every row when none is) emptied, after a confirm;
  // saving then takes their treatments off.
  clear() {
    const ticked = this.rows.filter( ( r ) => r.box.checked );
    const filled = ( ticked.length ? ticked : this.rows ).filter( ( r ) => r.input.value.trim() );
    if ( !filled.length ) return;
    if ( !window.confirm( I18n.get( "treatments.clear_confirm" ).replace( "{n}" , filled.length ) ) ) return;
    filled.forEach( ( r ) => { r.input.value = ""; } );
    ticked.forEach( ( r ) => { r.box.checked = false; } );
    this.render();
  },

  async save() {
    this.saving = true;
    this.render();
    try {
      for ( const b of this.list ) {
        const given = {};
        this.rows.filter( ( r ) => r.batch === b ).forEach( ( r ) => { given[ r.key ] = r.input.value.trim(); } );
        await Api.post( "/api/ais/batches/" + b.id + "/treatments" , { treatments: given } );
      }
    } catch ( error ) {
      App.showError( error.message );
      this.saving = false;
      this.render();
      return;
    }
    this.saving = false;
    Dom.toast( I18n.get( "treatments.saved" ) , "ok" );
    this.finish( true );
    this.modal.hide();
  },

  finish( saved ) {
    const resolve = this.resolve;
    this.resolve = null;
    if ( resolve ) resolve( saved );
  },
};
