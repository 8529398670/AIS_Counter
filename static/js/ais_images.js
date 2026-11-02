// The Process screen's dialogs: Images (which of the batch to step through,
// with previews and duplicates) and Open path (a folder on this machine, read
// by the server, for a new batch or one the Batches screen adds to). Ais
// (ais.js) owns the images; this file only edits their `included` flag, and
// only when the selection is confirmed.
const AisImages = {
  staged: [],            // the selection being edited, one boolean per image
  anchor: -1,            // last plain/Ctrl click, for Shift ranges
  hideDuplicates: true,
  thumbSide: 256,

  init() {
    this.modalEl = Dom.get( "ais-images-modal" );
    this.modal = bootstrap.Modal.getOrCreateInstance( this.modalEl );
    this.grid = Dom.get( "ais-images-grid" );
    this.observer = new IntersectionObserver( ( items ) => items.forEach( ( item ) => {
      if ( item.isIntersecting ) {
        this.observer.unobserve( item.target );
        this.loadThumb( Number( item.target.dataset.index ) , item.target.querySelector( ".ais-thumb" ) );
      }
    } ) , { root: this.grid.closest( ".modal-body" ) , rootMargin: "200px" } );

    Dom.get( "ais-images-open" ).addEventListener( "click" , () => this.open() );
    Dom.get( "ais-images-all" ).addEventListener( "click" , () => this.setVisible( true ) );
    Dom.get( "ais-images-none" ).addEventListener( "click" , () => this.setVisible( false ) );
    Dom.get( "ais-images-mine" ).addEventListener( "click" , () => this.selectMine() );
    Dom.get( "ais-images-use" ).addEventListener( "click" , () => this.confirm() );
    Dom.get( "ais-images-filter" ).addEventListener( "input" , () => this.applyFilter() );
    Dom.get( "ais-images-hide-dups" ).addEventListener( "change" , ( e ) => this.setHideDuplicates( e.target.checked ) );
    this.grid.addEventListener( "keydown" , ( e ) => {
      if ( ( e.ctrlKey || e.metaKey ) && ( e.key === "a" || e.key === "A" ) ) { e.preventDefault(); this.setVisible( true ); }
    } );
    this.modalEl.addEventListener( "keydown" , ( e ) => {
      if ( e.key === "Enter" && e.target.tagName !== "BUTTON" ) { e.preventDefault(); this.confirm(); }
    } );

    this.initPath();
  },

  // --- Images ----------------------------------------------------------------

  open() {
    if ( !Ais.images.length ) return;
    this.staged = Ais.images.map( ( entry ) => entry.included );
    this.anchor = -1;
    Dom.get( "ais-images-filter" ).value = "";
    const batch = Ais.batch || { name: "" };
    Dom.text( Dom.get( "ais-images-batch" ) , batch.path || batch.name );
    const dups = Ais.images.filter( ( entry ) => entry.dup_of != null ).length;
    Dom.show( Dom.get( "ais-images-dups" ) , dups > 0 );
    Dom.text( Dom.get( "ais-images-dups-count" ) , I18n.get( "ais.n_duplicates" ).replace( "{n}" , dups ) );
    // Hidden by default when the batch has duplicates nobody has included.
    Dom.show( Dom.get( "ais-images-mine" ) , Boolean( Ais.myKeys() ) );
    this.hideDuplicates = dups > 0 && Ais.images.every( ( entry ) => entry.dup_of == null || !entry.included );
    Dom.get( "ais-images-hide-dups" ).checked = this.hideDuplicates;
    this.render();
    this.modal.show();
    this.modalEl.addEventListener( "shown.bs.modal" , () => this.grid.focus() , { once: true } );
  },

  confirm( showIndex ) {
    Ais.images.forEach( ( entry , i ) => { entry.included = this.staged[ i ]; } );
    this.modal.hide();
    Ais.inclusionChanged( showIndex != null ? showIndex : Ais.index );
    Ais.uploadAll();
  },

  render() {
    this.observer.disconnect();
    Dom.clear( this.grid );
    Ais.images.forEach( ( entry , i ) => {
      const main = entry.files[ Ais.traced( entry ) ];
      const name = Ais.splitName( main.name );
      const pair = Ais.kind( entry ) === "pair";
      const czi = Ais.kind( entry ) === "czi";
      const count = Ais.acceptedCount( entry );
      const box = Dom.el( "input" , { class: "form-check-input ais-card-check" , attrs: { type: "checkbox" , tabindex: "-1" , "aria-label": main.name } } );
      const badges = [
        Dom.el( "span" , { class: "badge " + ( pair || czi ? "text-bg-secondary" : "text-bg-warning" ) ,
          text: I18n.get( czi ? "ais.czi" : pair ? "ais.pair" : "ais.single" ) } ),
      ];
      if ( entry.dup_of != null ) {
        badges.push( Dom.el( "span" , { class: "badge text-bg-danger" , text: I18n.get( "ais.duplicate_of" ).replace( "{n}" , entry.dup_of + 1 ) } ) );
      }
      if ( count ) badges.push( Dom.el( "span" , { class: "badge text-bg-success" , text: count + " AIS" } ) );
      if ( Ais.isComplete( entry ) ) badges.push( Dom.el( "i" , { class: "bi bi-check-circle-fill text-success" , attrs: { title: I18n.get( "ais.complete" ) } } ) );
      const owner = Ais.assigneeOf( entry );
      if ( owner != null ) {
        const me = Ais.me && owner === Ais.me.id;
        badges.push( Dom.el( "span" , { class: "ais-card-assignee " + ( me ? "text-primary fw-semibold" : "text-body-secondary" ) , children: [
          Dom.el( "i" , { class: "bi bi-person me-1" } ) , Dom.el( "span" , { text: Ais.assigneeName( owner ) } ) ] } ) );
      }
      if ( Ais.local.matlab ) badges.push( this.matlabMenu( entry , main.name ) );
      const card = Dom.el( "div" , {
        class: "ais-image-card" + ( i === Ais.index ? " ais-current" : "" ),
        attrs: { role: "option" , "data-index": String( i ) , title: main.name },
        children: [
          Dom.el( "div" , { class: "ais-thumb" , children: [ Dom.el( "i" , { class: "bi bi-image text-body-tertiary" } ) ] } ),
          box,
          Dom.el( "div" , { class: "ais-card-body" , children: [
            Dom.el( "div" , { class: "ais-card-name" , children: [
              Dom.el( "span" , { class: "text-body-secondary me-1" , text: ( i + 1 ) + "." } ),
              Dom.el( "span" , { class: "fw-semibold" , text: ( entry.dir ? entry.dir + "/" : "" ) + name.stem } ),
              Dom.el( "span" , { class: "text-body-secondary" , text: name.ext } ),
            ] } ),
            pair ? Dom.el( "div" , { class: "small text-body-secondary text-truncate" , text: "+ " + entry.files.raw.name } ) : Dom.el( "span" ),
            Dom.el( "div" , { class: "d-flex flex-wrap align-items-center gap-1 mt-1" , children: badges } ),
          ] } ),
        ],
        on: {
          click: ( e ) => this.onClick( i , e ),
          // Double-click opens the image: undo what its first click did to
          // the selection, include it, and confirm.
          dblclick: () => {
            if ( this.beforeClick ) this.staged = this.beforeClick;
            this.staged[ i ] = true;
            this.confirm( i );
          },
        },
      } );
      this.grid.appendChild( card );
      this.observer.observe( card );
    } );
    this.applyFilter();
  },

  // The card's MATLAB menu: its own action, never the selection or opening.
  matlabMenu( entry , fileName ) {
    const stop = ( e ) => e.stopPropagation();
    const item = ( mode , icon ) => Dom.el( "li" , { children: [ Dom.el( "button" , {
      class: "dropdown-item small",
      attrs: { type: "button" },
      children: [ Dom.el( "i" , { class: "bi " + icon + " me-2" } ) , Dom.el( "span" , { text: I18n.get( "ais.matlab_" + mode ) } ) ],
      on: { click: ( e ) => { stop( e ); Ais.verifyInMatlab( entry , mode ); } },
    } ) ] } );
    return Dom.el( "div" , {
      class: "dropdown ms-auto",
      on: { click: stop , dblclick: stop },
      children: [
        Dom.el( "button" , {
          class: "btn btn-sm btn-outline-secondary py-0 px-1 dropdown-toggle ais-card-matlab",
          attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , title: I18n.get( "ais.matlab" ) ,
            "aria-label": I18n.get( "ais.matlab" ) + ": " + fileName },
          children: [ Dom.el( "i" , { class: "bi bi-window-stack" } ) ],
        } ),
        Dom.el( "ul" , { class: "dropdown-menu dropdown-menu-end" , children: [ item( "open" , "bi-file-earmark-code" ) , item( "run" , "bi-play" ) ] } ),
      ],
    } );
  },

  // A card shows its thumbnail once it scrolls near view: decoded here
  // (tiff.js) when this browser picked the TIFF, else rendered by the server
  // -- which can for an Open-path file or one already uploaded (a .czi
  // always: tiff.js does not read them).
  async loadThumb( i , holder ) {
    const entry = Ais.images[ i ];
    if ( !entry || !holder ) return;
    const f = entry.files[ Ais.traced( entry ) ];
    // Picked on the Batches screen and still waiting to upload: read here too.
    const picked = f.file || Batches.fileFor( f.sha );
    if ( !entry.thumb ) {
      if ( picked && Ais.kind( entry ) !== "czi" ) {
        try {
          entry.thumb = await Tiff.thumbnail( picked , this.thumbSide );
        } catch ( error ) {
          entry.thumb = null;
        }
      } else if ( f.stored ) {
        entry.thumb = Dom.el( "img" , { attrs: { alt: "" , src: "/api/ais/files/" + f.sha + "/thumb.png" } } );
      }
      if ( !entry.thumb ) {
        holder.replaceChildren( Dom.el( "span" , { class: "small text-body-tertiary px-2 text-center" , text: I18n.get( "ais.not_uploaded" ) } ) );
        return;
      }
    }
    // A canvas can sit in one place only; cloning keeps the cached one intact.
    let node = entry.thumb;
    if ( node.tagName === "CANVAS" ) {
      const copy = document.createElement( "canvas" );
      copy.width = node.width;
      copy.height = node.height;
      copy.getContext( "2d" ).drawImage( node , 0 , 0 );
      node = copy;
    } else {
      node = node.cloneNode();
    }
    holder.replaceChildren( node );
  },

  visible() {
    return Dom.all( ".ais-image-card" , this.grid ).filter( ( card ) => !card.hidden ).map( ( card ) => Number( card.dataset.index ) );
  },

  applyFilter() {
    const q = Dom.get( "ais-images-filter" ).value.trim().toLowerCase();
    Dom.all( ".ais-image-card" , this.grid ).forEach( ( card ) => {
      const entry = Ais.images[ Number( card.dataset.index ) ];
      const names = ( entry.dir + " " + Object.values( entry.files ).map( ( f ) => f.name ).join( " " ) ).toLowerCase();
      card.hidden = ( Boolean( q ) && !names.includes( q ) ) || ( this.hideDuplicates && entry.dup_of != null );
    } );
    this.refresh();
  },

  // Hiding duplicates also leaves them out; showing them again does not add
  // them back by itself.
  setHideDuplicates( on ) {
    this.hideDuplicates = on;
    if ( on ) Ais.images.forEach( ( entry , i ) => { if ( entry.dup_of != null ) this.staged[ i ] = false; } );
    this.applyFilter();
  },

  // Like a file list: click selects only that image, Ctrl/Cmd-click toggles
  // one, Shift-click selects the range from the anchor (adding to the rest
  // with Ctrl/Cmd held). The checkbox toggles one, or with Shift sets the
  // range to its new state. Ranges run over the cards on show.
  onClick( i , event ) {
    if ( event.detail > 1 ) return;   // the second click of a double-click
    this.beforeClick = this.staged.slice();
    const additive = event.ctrlKey || event.metaKey;
    const shown = this.visible();
    const from = shown.indexOf( this.anchor >= 0 ? this.anchor : i );
    const to = shown.indexOf( i );
    const range = from >= 0 ? shown.slice( Math.min( from , to ) , Math.max( from , to ) + 1 ) : [ i ];
    if ( event.target.type === "checkbox" ) {
      const on = event.target.checked;
      ( event.shiftKey ? range : [ i ] ).forEach( ( k ) => { this.staged[ k ] = on; } );
      this.anchor = i;
    } else if ( event.shiftKey ) {
      if ( !additive ) this.staged = this.staged.map( () => false );
      range.forEach( ( k ) => { this.staged[ k ] = true; } );
    } else if ( additive ) {
      this.staged[ i ] = !this.staged[ i ];
      this.anchor = i;
    } else {
      this.staged = this.staged.map( ( _ , k ) => k === i );
      this.anchor = i;
    }
    this.refresh();
  },

  // Exactly the images assigned to whoever is signed in.
  selectMine() {
    const mine = Ais.myKeys();
    if ( !mine ) return;
    Ais.images.forEach( ( entry , i ) => { this.staged[ i ] = mine.has( entry.key ); } );
    this.refresh();
  },

  setVisible( on ) {
    this.visible().forEach( ( k ) => { this.staged[ k ] = on; } );
    this.refresh();
  },

  // Update checkboxes and counts without rebuilding the cards.
  refresh() {
    Dom.all( ".ais-image-card" , this.grid ).forEach( ( card ) => {
      const on = this.staged[ Number( card.dataset.index ) ];
      card.classList.toggle( "ais-selected" , on );
      card.setAttribute( "aria-selected" , String( on ) );
      card.querySelector( ".ais-card-check" ).checked = on;
    } );
    const n = this.staged.filter( Boolean ).length;
    Dom.text( Dom.get( "ais-images-selected" ) , I18n.get( "ais.n_selected" ).replace( "{n}" , n ).replace( "{total}" , this.staged.length ) );
    const done = Ais.images.filter( ( entry , i ) => this.staged[ i ] && Ais.isComplete( entry ) ).length;
    Dom.text( Dom.get( "ais-images-progress" ) , I18n.get( "ais.completed" ).replace( "{done}" , done ).replace( "{total}" , n ) );
    const use = Dom.get( "ais-images-use" );
    Dom.text( use , I18n.get( "ais.use_n" ).replace( "{n}" , n ) );
    use.disabled = n === 0;
  },

  // --- Open path -------------------------------------------------------------

  initPath() {
    this.pathModalEl = Dom.get( "ais-path-modal" );
    this.pathModal = bootstrap.Modal.getOrCreateInstance( this.pathModalEl );
    this.listing = null;
    this.pathTarget = null;   // the batch to add the folder to, or null for a new one
    Dom.get( "ais-open-path" ).addEventListener( "click" , () => this.openPathDialog( null ) );
    Dom.get( "ais-path-form" ).addEventListener( "submit" , ( e ) => { e.preventDefault(); this.browse( Dom.get( "ais-path-input" ).value ); } );
    Dom.get( "ais-path-choose" ).addEventListener( "click" , () => this.chooseNative() );
    Dom.get( "ais-path-open" ).addEventListener( "click" , () => this.openListing() );
  },

  // Folders opened by path before, newest first (from the shared batches).
  async recentPaths() {
    try {
      const list = ( await Api.request( "/api/ais/batches" ) ).batches;
      const newest = list.filter( ( b ) => b.path ).sort( ( a , b ) => b.id - a.id );
      return Array.from( new Set( newest.map( ( b ) => b.path ) ) ).slice( 0 , 8 );
    } catch ( error ) {
      return [];
    }
  },

  // target: a Batches list row to add the folder to, or null to open a new batch.
  async openPathDialog( target ) {
    this.pathTarget = target || null;
    Dom.show( Dom.get( "ais-path-choose" ) , Ais.local.platform === "mac" );
    this.pathModal.show();
    const recent = await this.recentPaths();
    const holder = Dom.get( "ais-path-recent" );
    Dom.clear( holder );
    recent.forEach( ( path ) => holder.appendChild( Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary text-truncate ais-recent",
      text: path.replace( /[\\/]+$/ , "" ).split( /[\\/]/ ).pop() || path,
      attrs: { type: "button" , title: path },
      on: { click: () => this.browse( path ) },
    } ) ) );
    this.browse( ( target && target.path ) || ( Ais.batch && Ais.batch.path ) || recent[ 0 ] || "~" );
  },

  async browse( path ) {
    const error = Dom.get( "ais-path-error" );
    Dom.show( error , false );
    try {
      this.listing = await Api.post( "/api/ais/local/list" , { path: path } );
    } catch ( failure ) {
      Dom.text( error , failure.message );
      Dom.show( error , true );
      return;
    }
    const l = this.listing;
    Dom.get( "ais-path-input" ).value = l.path;
    const list = Dom.get( "ais-path-list" );
    Dom.clear( list );
    const row = ( icon , text , onClick , muted ) => list.appendChild( Dom.el( onClick ? "button" : "div" , {
      class: "list-group-item " + ( onClick ? "list-group-item-action " : "" ) + ( muted ? "text-body-secondary small" : "" ),
      attrs: onClick ? { type: "button" } : {},
      children: [ Dom.el( "i" , { class: "bi " + icon + " me-2" } ) , Dom.el( "span" , { text: text } ) ],
      on: onClick ? { click: onClick } : {},
    } ) );
    const sep = l.path.includes( "\\" ) && !l.path.includes( "/" ) ? "\\" : "/";
    if ( l.parent ) row( "bi-arrow-90deg-up" , ".." , () => this.browse( l.parent ) );
    l.dirs.forEach( ( d ) => row( "bi-folder" , d , () => this.browse( l.path.replace( /[\\/]+$/ , "" ) + sep + d ) ) );
    l.files.slice( 0 , 200 ).forEach( ( f ) => row( "bi-file-earmark-image" , f.name , null , true ) );
    const n = l.files.length;
    Dom.text( Dom.get( "ais-path-summary" ) , I18n.get( "ais.path_tiffs" ).replace( "{n}" , n ) );
    // Subfolders are read too (app/analysis/local.py), so a folder of folders opens.
    Dom.get( "ais-path-open" ).disabled = n === 0 && !l.dirs.length;
  },

  async chooseNative() {
    try {
      const picked = await Api.post( "/api/ais/local/choose" , {} );
      if ( picked.path ) this.browse( picked.path );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  openListing() {
    const l = this.listing;
    if ( !l || ( !l.files.length && !l.dirs.length ) ) return;
    this.pathModal.hide();
    const target = this.pathTarget;
    if ( target ) {
      Batches.addPath( target , l.path );
      return;
    }
    // Let the path dialog finish closing before the Images dialog opens.
    this.pathModalEl.addEventListener( "hidden.bs.modal" , () => Ais.openPath( l.path ) , { once: true } );
  },
};
