// The Assign dialog (admins): split a batch among people by share, one
// slider each. Adding or removing someone resets everyone to an even split;
// moving one slider rescales the others into what is left, so the shares
// always total 100 %. The server deals the images out
// (app/models/ais.py assign): a contiguous run each, duplicates left out,
// finished images kept by whoever had them.
const AisAssign = {
  batch: null,           // the Batches screen's row being assigned
  shares: [],            // [{ user_id, name, percent }], whole percents
  team: [],

  init() {
    this.modalEl = Dom.get( "ais-assign-modal" );
    this.modal = bootstrap.Modal.getOrCreateInstance( this.modalEl );
    Dom.get( "ais-assign-add" ).addEventListener( "click" , () => this.add() );
    Dom.get( "ais-assign-save" ).addEventListener( "click" , () => this.save( this.shares ) );
    Dom.get( "ais-assign-clear" ).addEventListener( "click" , () => this.save( [] ) );
    this.modalEl.addEventListener( "hidden.bs.modal" , () => Batches.refresh( true ) );
  },

  async open( batch ) {
    this.batch = batch;
    try {
      this.team = await Api.listTeam();
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    const names = new Map( this.team.map( ( u ) => [ u.id , u.display_name ] ) );
    this.shares = batch.assignees.map( ( a ) => ( { user_id: a.user_id , name: names.get( a.user_id ) || a.name , percent: a.percent } ) );
    this.roundShares();
    Dom.text( Dom.get( "ais-assign-batch" ) , batch.path || batch.name );
    Dom.get( "ais-assign-clear" ).disabled = !batch.assignees.length;
    this.render();
    this.modal.show();
  },

  // n parts of total by weight, largest remainder first: they sum to total.
  split( total , weights ) {
    const sum = weights.reduce( ( a , b ) => a + b , 0 );
    if ( total <= 0 || sum <= 0 ) return weights.map( () => 0 );
    const exact = weights.map( ( w ) => total * w / sum );
    const counts = exact.map( Math.floor );
    const order = exact.map( ( x , i ) => i ).sort( ( a , b ) => ( exact[ b ] - counts[ b ] ) - ( exact[ a ] - counts[ a ] ) || a - b );
    order.slice( 0 , total - counts.reduce( ( a , b ) => a + b , 0 ) ).forEach( ( i ) => { counts[ i ] += 1; } );
    return counts;
  },

  // Saved shares can be fractional (66.67); the sliders work in whole percents.
  roundShares() {
    this.split( 100 , this.shares.map( ( s ) => s.percent ) ).forEach( ( p , i ) => { this.shares[ i ].percent = p; } );
  },

  even() {
    this.split( 100 , this.shares.map( () => 1 ) ).forEach( ( p , i ) => { this.shares[ i ].percent = p; } );
  },

  add() {
    const select = Dom.get( "ais-assign-who" );
    const id = Number( select.value );
    const user = this.team.find( ( u ) => u.id === id );
    if ( !user ) return;
    this.shares.push( { user_id: id , name: user.display_name , percent: 0 } );
    this.even();
    this.render();
  },

  remove( i ) {
    this.shares.splice( i , 1 );
    this.even();
    this.render();
  },

  // One slider moved to v: the others share 100 - v in their current
  // proportions, at least 1 % each.
  slide( i , v ) {
    const n = this.shares.length;
    const value = Math.max( 1 , Math.min( 100 - ( n - 1 ) , Math.round( v ) ) );
    const others = this.shares.map( ( s , j ) => j ).filter( ( j ) => j !== i );
    let weights = others.map( ( j ) => this.shares[ j ].percent );
    if ( weights.every( ( w ) => w <= 0 ) ) weights = others.map( () => 1 );
    const extra = this.split( 100 - value - others.length , weights );
    this.shares[ i ].percent = value;
    others.forEach( ( j , k ) => { this.shares[ j ].percent = 1 + extra[ k ]; } );
    this.renderValues();
  },

  // Images the split would deal out (duplicates are left out of it).
  eligible() {
    return this.batch ? this.batch.images - this.batch.duplicates : 0;
  },

  render() {
    const rows = Dom.get( "ais-assign-rows" );
    Dom.clear( rows );
    Dom.show( Dom.get( "ais-assign-none" ) , !this.shares.length );
    this.shares.forEach( ( share , i ) => {
      const slider = Dom.el( "input" , {
        class: "form-range flex-grow-1",
        attrs: { type: "range" , min: "1" , max: "100" , step: "1" , "aria-label": share.name , "data-share": String( i ) },
        on: { input: ( e ) => this.slide( i , Number( e.target.value ) ) },
      } );
      rows.appendChild( Dom.el( "div" , { class: "ais-assign-row" , children: [
        Dom.el( "div" , { class: "d-flex align-items-center gap-2" , children: [
          Dom.el( "span" , { class: "fw-semibold me-auto text-truncate" , text: share.name } ),
          Dom.el( "span" , { class: "small text-body-secondary" , attrs: { "data-count": String( i ) } } ),
          Dom.el( "span" , { class: "ais-assign-percent" , attrs: { "data-percent": String( i ) } } ),
          Dom.el( "button" , {
            class: "btn btn-sm btn-link text-danger p-0",
            attrs: { type: "button" , title: I18n.get( "ais.assign_remove" ) , "aria-label": I18n.get( "ais.assign_remove" ) + ": " + share.name },
            children: [ Dom.el( "i" , { class: "bi bi-x-lg" } ) ],
            on: { click: () => this.remove( i ) },
          } ),
        ] } ),
        slider,
      ] } ) );
    } );
    // Only people not in the split yet can be added.
    const select = Dom.get( "ais-assign-who" );
    Dom.clear( select );
    const taken = new Set( this.shares.map( ( s ) => s.user_id ) );
    const free = this.team.filter( ( u ) => !taken.has( u.id ) );
    free.forEach( ( u ) => select.appendChild( Dom.el( "option" , { text: u.display_name , attrs: { value: String( u.id ) } } ) ) );
    select.disabled = !free.length;
    Dom.get( "ais-assign-add" ).disabled = !free.length;
    Dom.get( "ais-assign-save" ).disabled = !this.shares.length;
    this.renderValues();
  },

  renderValues() {
    const counts = this.split( this.eligible() , this.shares.map( ( s ) => s.percent ) );
    const alone = this.shares.length === 1;
    this.shares.forEach( ( share , i ) => {
      const slider = this.modalEl.querySelector( "[data-share='" + i + "']" );
      slider.value = String( share.percent );
      slider.disabled = alone;
      Dom.text( this.modalEl.querySelector( "[data-percent='" + i + "']" ) , share.percent + " %" );
      Dom.text( this.modalEl.querySelector( "[data-count='" + i + "']" ) , I18n.get( "ais.assign_images" ).replace( "{n}" , counts[ i ] ) );
    } );
  },

  async save( shares ) {
    let saved;
    try {
      saved = await Api.post( "/api/ais/batches/" + this.batch.id + "/assign" ,
        { shares: shares.map( ( s ) => ( { user_id: s.user_id , percent: s.percent } ) ) } );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    if ( Ais.batch && Ais.batch.id === saved.id ) Ais.applyAssignment( saved );
    this.modal.hide();
  },
};
