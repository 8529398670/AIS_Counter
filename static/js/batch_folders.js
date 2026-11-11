// The Batches screen's folders (app/models/ais.py): nested, the team's, so
// everyone sees them and only admins change them. Batches (batches.js) hands
// over each polled list and draws its cards; this file lays them out.
//
// Two ways to show them, picked in Settings (Settings.batchesView):
//   drill -- one folder at a time: a path back up, its folders as tiles, then
//            its batches. The folder open is in the hash (#batches/folder/12),
//            so Back, Forward, reload and a pasted link land there.
//   tree  -- every folder a heading that opens and closes (remembered in this
//            browser), its folders and batches under it.
// With the filter typed or Mine only on, both search every folder and show
// what matches flat, each card saying which folder it is in.
//
// Admins file a batch by dragging its card onto a folder (tile, heading or a
// step of the path) or from its menu (Move to folder); folders have a menu
// of their own. Deleting a folder loses nothing: what was in it moves up,
// and the folder itself goes to the trash (trash.js), from where it comes back.
// Admins can also Compare a folder: every batch in it and the folders inside
// it, one culture each, through Compare.run (compare.js) as Compare selected.
const BatchFolders = {
  folders: [],
  byId: new Map(),
  children: new Map(),   // parent id (null at the top) -> its folders, in order
  openKey: "batches-tree-open",
  open: null,            // folder ids open in the tree view
  editing: null,         // { id } renaming, or { parent } making a folder
  moving: null,          // { batchIds } or { folderId } for the Move dialog

  init() {
    this.open = this.loadOpen();
    Dom.get( "batches-folder-form" ).addEventListener( "submit" , ( e ) => { e.preventDefault(); this.saveName(); } );
    Dom.get( "batches-move-form" ).addEventListener( "submit" , ( e ) => { e.preventDefault(); this.saveMove(); } );
    Dom.get( "batches-folder-modal" ).addEventListener( "shown.bs.modal" , () => {
      const input = Dom.get( "batches-folder-name" );
      input.focus();
      input.select();
    } );
    const add = Dom.get( "batches-new-folder" );
    Dom.show( add , Batches.admin() );
    add.addEventListener( "click" , () => this.openName( null , this.here() ) );
    const move = Dom.get( "batches-move-selected" );
    move.addEventListener( "click" , () => this.openMove( { batchIds: [ ...Batches.selected ] } ) );
    Settings.onChange( () => { if ( this.view !== Settings.batchesView() ) Batches.render(); } );
  },

  // --- the folders ---------------------------------------------------------------

  set( folders ) {
    this.folders = folders || [];
    this.byId = new Map( this.folders.map( ( f ) => [ f.id , f ] ) );
    this.children = new Map();
    this.folders.forEach( ( f ) => {
      const parent = this.byId.has( f.parent_id ) ? f.parent_id : null;
      if ( !this.children.has( parent ) ) this.children.set( parent , [] );
      this.children.get( parent ).push( f );
    } );
  },

  childrenOf( id ) {
    return this.children.get( id ) || [];
  },

  // A batch's folder, null at the top (or in a folder that has gone).
  folderOf( b ) {
    return this.byId.has( b.folder_id ) ? b.folder_id : null;
  },

  // The folders from the top down to id.
  path( id ) {
    const out = [];
    for ( let at = this.byId.get( id ) ; at && out.length <= this.folders.length ; at = this.byId.get( at.parent_id ) ) out.unshift( at );
    return out;
  },

  pathText( id ) {
    return [ I18n.get( "batches.folders_top" ) , ...this.path( id ).map( ( f ) => f.name ) ].join( " › " );
  },

  // id and every folder inside it.
  subtree( id ) {
    const out = new Set( [ id ] );
    const walk = ( at ) => this.childrenOf( at ).forEach( ( f ) => { out.add( f.id ); walk( f.id ); } );
    walk( id );
    return out;
  },

  // The folder the drill view has open (null: the top), from the hash.
  current() {
    const parts = window.location.hash.replace( /^#/ , "" ).split( "/" );
    const id = parts[ 1 ] === "folder" ? Number( parts[ 2 ] ) : NaN;
    return this.byId.has( id ) ? id : null;
  },

  go( id ) {
    window.location.hash = id == null ? "#batches" : "#batches/folder/" + id;
  },

  // Where something new goes: the folder open, in the drill view.
  here() {
    return Settings.batchesView() === "drill" ? this.current() : null;
  },

  searching() {
    return Boolean( Dom.get( "batches-filter" ).value.trim() ) || Dom.get( "batches-mine" ).checked;
  },

  // What Export all takes: the batches shown, and in the drill view only
  // those in the folder open and the folders inside it.
  inView( shown ) {
    if ( this.searching() || Settings.batchesView() !== "drill" ) return shown;
    const here = this.current();
    if ( here == null ) return shown;
    const inside = this.subtree( here );
    return shown.filter( ( b ) => inside.has( this.folderOf( b ) ) );
  },

  // Batches, images included and done in a folder and everything inside it,
  // over the batches shown (archived only with Show archived).
  counts( id , shown ) {
    const inside = this.subtree( id );
    const out = { batches: 0 , done: 0 , total: 0 };
    shown.forEach( ( b ) => {
      if ( !inside.has( this.folderOf( b ) ) ) return;
      out.batches += 1;
      out.done += b.completed || 0;
      out.total += Batches.includedOf( b );
    } );
    return out;
  },

  // --- drawing -------------------------------------------------------------------

  // Lays out the batches shown (already filtered) into holder (the folders
  // above) and list (the cards); card(b) draws one. Answers whether anything
  // is on screen.
  render( holder , list , shown , card ) {
    this.view = Settings.batchesView();
    Dom.clear( holder );
    if ( this.searching() ) {
      shown.forEach( ( b ) => list.appendChild( this.labelled( card( b ) , b ) ) );
      return shown.length > 0;
    }
    if ( this.view === "tree" ) {
      this.childrenOf( null ).forEach( ( f ) => holder.appendChild( this.branch( f , shown , card ) ) );
      const loose = shown.filter( ( b ) => this.folderOf( b ) == null );
      loose.forEach( ( b ) => list.appendChild( card( b ) ) );
      return this.folders.length > 0 || loose.length > 0;
    }
    const here = this.current();
    const crumbs = this.breadcrumb( here );
    holder.appendChild( here != null && Batches.admin()
      ? Dom.el( "div" , { class: "d-flex align-items-center flex-wrap gap-2" , children: [ crumbs , this.compareButton( here , false ) ] } )
      : crumbs );
    const tiles = this.childrenOf( here );
    if ( tiles.length ) holder.appendChild( Dom.el( "div" , { class: "batches-tiles" ,
      children: tiles.map( ( f ) => this.tile( f , shown ) ) } ) );
    const mine = shown.filter( ( b ) => this.folderOf( b ) === here );
    mine.forEach( ( b ) => list.appendChild( card( b ) ) );
    if ( here != null && !tiles.length && !mine.length ) {
      holder.appendChild( Dom.el( "p" , { class: "text-body-secondary" , text: I18n.get( "batches.folder_empty" ) } ) );
      return true;
    }
    return tiles.length > 0 || mine.length > 0;
  },

  // A card found by a search says where it lives.
  labelled( card , b ) {
    const id = this.folderOf( b );
    if ( id == null ) return card;
    const body = card.querySelector( ".card-body" );
    body.insertBefore( Dom.el( "button" , { class: "btn btn-link btn-sm p-0 mb-1 text-body-secondary text-truncate batches-in-folder" ,
      attrs: { type: "button" , title: I18n.get( "batches.folder_open" ) } ,
      on: { click: () => this.reveal( id ) } ,
      children: [ Dom.el( "i" , { class: "bi bi-folder2 me-1" } ) , Dom.el( "span" , { text: this.pathText( id ) } ) ] } ) , body.firstChild );
    return card;
  },

  // Clears the search and shows folder id.
  reveal( id ) {
    Dom.get( "batches-filter" ).value = "";
    Dom.get( "batches-mine" ).checked = false;
    if ( Settings.batchesView() === "tree" ) {
      this.path( id ).forEach( ( f ) => this.open.add( f.id ) );
      this.saveOpen();
      Batches.render();
    } else {
      this.go( id );
      Batches.render();
    }
  },

  breadcrumb( here ) {
    const steps = [ { id: null , name: I18n.get( "batches.folders_top" ) } , ...this.path( here ) ];
    return Dom.el( "nav" , { class: "batches-crumbs" , attrs: { "aria-label": I18n.get( "batches.folders_breadcrumb" ) } , children: [
      Dom.el( "ol" , { class: "breadcrumb mb-2" , children: steps.map( ( step , i ) => {
        const last = i === steps.length - 1;
        const item = Dom.el( "li" , { class: "breadcrumb-item" + ( last ? " active" : "" ) ,
          attrs: last ? { "aria-current": "page" } : {} , children: [
            last ? Dom.el( "span" , { class: "fw-semibold" , text: step.name } )
              : Dom.el( "a" , { text: step.name , attrs: { href: step.id == null ? "#batches" : "#batches/folder/" + step.id } } ),
          ] } );
        if ( !last ) this.dropTarget( item , step.id );
        return item;
      } ) } ),
    ] } );
  },

  countLine( c ) {
    return I18n.get( "batches.folder_counts" ).replace( "{batches}" , c.batches ).replace( "{done}" , c.done ).replace( "{total}" , c.total );
  },

  tile( f , shown ) {
    const c = this.counts( f.id , shown );
    const share = c.total ? 100 * c.done / c.total : 0;
    const bar = Dom.el( "div" , { class: "progress batches-bar mt-2" , attrs: { role: "progressbar" ,
      "aria-label": I18n.get( "batches.completed" ) , "aria-valuenow": String( c.done ) , "aria-valuemin": "0" , "aria-valuemax": String( c.total ) } ,
      children: [ Dom.el( "div" , { class: "progress-bar" + ( c.total && c.done >= c.total ? " bg-success" : "" ) } ) ] } );
    bar.firstChild.style.width = share + "%";
    const tile = Dom.el( "div" , { class: "card batches-tile" , children: [ Dom.el( "div" , { class: "card-body" , children: [
      Dom.el( "div" , { class: "d-flex align-items-center gap-2 min-w-0" , children: [
        Dom.el( "a" , { class: "stretched-link text-truncate fw-semibold batches-tile-name me-auto" , attrs: { href: "#batches/folder/" + f.id } ,
          children: [ Dom.el( "i" , { class: "bi bi-folder-fill me-2 text-warning" } ) , Dom.el( "span" , { text: f.name } ) ] } ),
        ...( Batches.admin() ? [ this.compareButton( f.id , true ) , this.menu( f ) ] : [] ),
      ] } ),
      Dom.el( "div" , { class: "small text-body-secondary mt-1" , text: this.countLine( c ) } ),
      ...( c.total ? [ bar ] : [] ),
    ] } ) ] } );
    this.dropTarget( tile , f.id );
    return tile;
  },

  // One folder in the tree view: its heading, then (open) its folders and batches.
  branch( f , shown , card ) {
    const isOpen = this.open.has( f.id );
    const c = this.counts( f.id , shown );
    const head = Dom.el( "div" , { class: "batches-branch-head" , children: [
      Dom.el( "button" , { class: "btn btn-sm btn-link text-body text-decoration-none p-0 d-flex align-items-center gap-2 min-w-0" ,
        attrs: { type: "button" , "aria-expanded": String( isOpen ) } , on: { click: () => this.toggle( f.id ) } , children: [
          Dom.el( "i" , { class: "bi " + ( isOpen ? "bi-chevron-down" : "bi-chevron-right" ) } ),
          Dom.el( "i" , { class: "bi " + ( isOpen ? "bi-folder2-open" : "bi-folder-fill" ) + " text-warning" } ),
          Dom.el( "span" , { class: "fw-semibold text-truncate" , text: f.name } ),
        ] } ),
      Dom.el( "span" , { class: "small text-body-secondary text-nowrap me-auto" , text: this.countLine( c ) } ),
      ...( Batches.admin() ? [ this.compareButton( f.id , true ) , this.menu( f ) ] : [] ),
    ] } );
    this.dropTarget( head , f.id );
    const children = [ head ];
    if ( isOpen ) {
      const inner = Dom.el( "div" , { class: "batches-branch-body" } );
      this.childrenOf( f.id ).forEach( ( sub ) => inner.appendChild( this.branch( sub , shown , card ) ) );
      const here = shown.filter( ( b ) => this.folderOf( b ) === f.id );
      if ( here.length ) inner.appendChild( Dom.el( "div" , { class: "batches-list" , children: here.map( card ) } ) );
      if ( !here.length && !this.childrenOf( f.id ).length ) {
        inner.appendChild( Dom.el( "p" , { class: "small text-body-secondary mb-0" , text: I18n.get( "batches.folder_empty" ) } ) );
      }
      children.push( inner );
    }
    return Dom.el( "section" , { class: "batches-branch" , children: children } );
  },

  toggle( id ) {
    if ( this.open.has( id ) ) this.open.delete( id );
    else this.open.add( id );
    this.saveOpen();
    Batches.render();
  },

  loadOpen() {
    try {
      const saved = JSON.parse( window.localStorage.getItem( this.openKey ) || "[]" );
      return new Set( Array.isArray( saved ) ? saved.filter( Number.isInteger ) : [] );
    } catch ( error ) {
      return new Set();
    }
  },

  saveOpen() {
    try {
      window.localStorage.setItem( this.openKey , JSON.stringify( [ ...this.open ] ) );
    } catch ( error ) {
      // Not remembered, still open now.
    }
  },

  // A batch card dragged by its grip (Batches.dragHandlers) and let go on
  // element files it in folder id (null: the top).
  dropTarget( element , id ) {
    if ( !Batches.admin() ) return;
    const fits = () => Batches.dragging != null;
    element.addEventListener( "dragover" , ( e ) => {
      if ( !fits() ) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      element.classList.add( "batches-drop-into" );
    } );
    element.addEventListener( "dragleave" , ( e ) => {
      if ( !element.contains( e.relatedTarget ) ) element.classList.remove( "batches-drop-into" );
    } );
    element.addEventListener( "drop" , ( e ) => {
      if ( !fits() ) return;
      e.preventDefault();
      element.classList.remove( "batches-drop-into" );
      const batchId = Batches.dragging;
      Batches.dragging = null;
      this.moveBatches( [ batchId ] , id );
    } );
  },

  // --- comparing a folder (admins) -----------------------------------------------

  // The batches a folder's Compare takes: shown (so archived ones only with
  // Show archived), with images, in it or in a folder inside it.
  compareSet( id ) {
    const inside = this.subtree( id );
    return Batches.shown().filter( ( b ) => b.images && inside.has( this.folderOf( b ) ) );
  },

  compareFolder( id ) {
    Batches.compareList( this.compareSet( id ) );
  },

  // The bar-chart button (small: on a tile or heading; else with its words,
  // beside the path), disabled with fewer than two batches to compare.
  compareButton( id , small ) {
    const n = this.compareSet( id ).length;
    const ready = n >= 2;
    const title = I18n.get( ready ? "batches.folder_compare_help" : "batches.folder_compare_few" );
    const button = Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary batches-folder-compare" + ( small ? " border-0 py-0" : "" ) ,
      attrs: { type: "button" , "aria-label": I18n.get( "batches.folder_compare" ) + ": " + ( this.byId.get( id ) || {} ).name } ,
      on: { click: () => this.compareFolder( id ) } ,
      children: [ Dom.el( "i" , { class: "bi bi-bar-chart-line" + ( small ? "" : " me-1" ) } ) ,
        ...( small ? [] : [ Dom.el( "span" , { text: I18n.get( "batches.folder_compare" ) } ) ] ) ],
    } );
    button.disabled = !ready;
    // A disabled button gets no hover: its wrapper carries the title.
    return Dom.el( "span" , { class: "d-inline-block batches-folder-compare-wrap" , attrs: { title: title } , children: [ button ] } );
  },

  // --- changing (admins) ---------------------------------------------------------

  menu( f ) {
    const siblings = this.childrenOf( this.byId.has( f.parent_id ) ? f.parent_id : null );
    const at = siblings.findIndex( ( x ) => x.id === f.id );
    const items = [
      Batches.menuItem( "bi-pencil" , I18n.get( "batches.folder_rename" ) , () => this.openName( f.id , null ) ),
      Batches.menuItem( "bi-folder-symlink" , I18n.get( "batches.folder_move" ) , () => this.openMove( { folderId: f.id } ) ),
    ];
    if ( this.compareSet( f.id ).length >= 2 ) {
      items.push( Batches.menuItem( "bi-bar-chart-line" , I18n.get( "batches.folder_compare" ) , () => this.compareFolder( f.id ) ) );
    }
    if ( at > 0 ) items.push( Batches.menuItem( "bi-chevron-up" , I18n.get( "batches.move_up" ) , () => this.reorder( f , siblings , -1 ) ) );
    if ( at < siblings.length - 1 ) items.push( Batches.menuItem( "bi-chevron-down" , I18n.get( "batches.move_down" ) , () => this.reorder( f , siblings , 1 ) ) );
    items.push( Dom.el( "li" , { children: [ Dom.el( "hr" , { class: "dropdown-divider" } ) ] } ) );
    items.push( Batches.menuItem( "bi-trash" , I18n.get( "batches.folder_delete" ) , () => this.remove( f ) , "text-danger" ) );
    // Above the tile's stretched link, so it opens the menu, not the folder.
    const group = Batches.dropdown( Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary border-0 py-0" ,
      attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" ,
        title: I18n.get( "batches.folder_menu" ) , "aria-label": I18n.get( "batches.folder_menu" ) + ": " + f.name } ,
      children: [ Dom.el( "i" , { class: "bi bi-three-dots" } ) ],
    } ) , items , true );
    group.classList.add( "batches-folder-menu" );
    return group;
  },

  // The name dialog: renaming folder id, or (id null) a new folder in parent.
  openName( id , parent ) {
    this.editing = id == null ? { parent: parent } : { id: id };
    Dom.text( Dom.get( "batches-folder-title" ) , I18n.get( id == null ? "batches.folder_new" : "batches.folder_rename" ) );
    Dom.text( Dom.get( "batches-folder-where" ) , id == null ? this.pathText( parent ) : this.pathText( this.byId.get( id ).parent_id ) );
    Dom.get( "batches-folder-name" ).value = id == null ? "" : this.byId.get( id ).name;
    bootstrap.Modal.getOrCreateInstance( Dom.get( "batches-folder-modal" ) ).show();
  },

  async saveName() {
    const name = Dom.get( "batches-folder-name" ).value.trim();
    const editing = this.editing;
    if ( !name || !editing ) return;
    try {
      if ( editing.id != null ) {
        await Api.post( "/api/ais/folders/" + editing.id + "/rename" , { name: name } );
      } else {
        const folder = await Api.post( "/api/ais/folders" , { name: name , parent_id: editing.parent } );
        Dom.toast( I18n.get( "batches.folder_created" ).replace( "{name}" , folder.name ) );
        if ( editing.parent != null ) { this.open.add( editing.parent ); this.saveOpen(); }
      }
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    this.editing = null;
    bootstrap.Modal.getOrCreateInstance( Dom.get( "batches-folder-modal" ) ).hide();
    await Batches.refresh( true );
  },

  // The Move dialog, for batches ({ batchIds }) or a folder ({ folderId }):
  // every folder, indented, a folder's own branch left out for itself.
  openMove( moving ) {
    if ( moving.batchIds && !moving.batchIds.length ) return;
    this.moving = moving;
    const select = Dom.get( "batches-move-to" );
    Dom.clear( select );
    const barred = moving.folderId != null ? this.subtree( moving.folderId ) : new Set();
    const option = ( value , text , depth , disabled ) => select.appendChild( Dom.el( "option" , {
      text: "  ".repeat( depth ) + text , attrs: Object.assign( { value: value } , disabled ? { disabled: "" } : {} ) } ) );
    option( "" , I18n.get( "batches.folders_top" ) , 0 , false );
    const walk = ( parent , depth ) => this.childrenOf( parent ).forEach( ( f ) => {
      option( String( f.id ) , f.name , depth , barred.has( f.id ) );
      walk( f.id , depth + 1 );
    } );
    walk( null , 1 );
    let from;
    if ( moving.folderId != null ) {
      from = this.byId.get( moving.folderId ).parent_id;
      Dom.text( Dom.get( "batches-move-what" ) , this.byId.get( moving.folderId ).name );
    } else {
      const picked = ( Batches.list || [] ).filter( ( b ) => moving.batchIds.includes( b.id ) );
      from = picked.length === 1 ? this.folderOf( picked[ 0 ] ) : this.here();
      Dom.text( Dom.get( "batches-move-what" ) , picked.length === 1 ? picked[ 0 ].name
        : I18n.get( "batches.n_batches" ).replace( "{n}" , picked.length ) );
    }
    select.value = from == null ? "" : String( from );
    bootstrap.Modal.getOrCreateInstance( Dom.get( "batches-move-modal" ) ).show();
  },

  async saveMove() {
    const moving = this.moving;
    if ( !moving ) return;
    const value = Dom.get( "batches-move-to" ).value;
    const to = value === "" ? null : Number( value );
    bootstrap.Modal.getOrCreateInstance( Dom.get( "batches-move-modal" ) ).hide();
    this.moving = null;
    if ( moving.folderId != null ) {
      try {
        await Api.post( "/api/ais/folders/" + moving.folderId + "/move" , { parent_id: to } );
      } catch ( error ) {
        App.showError( error.message );
      }
      await Batches.refresh( true );
    } else {
      await this.moveBatches( moving.batchIds , to );
    }
  },

  async moveBatches( ids , to ) {
    try {
      const out = await Api.post( "/api/ais/batches/move" , { ids: ids , folder_id: to } );
      // Filed: what was ticked is done with.
      Batches.selected.clear();
      const name = to == null ? I18n.get( "batches.folders_top" ) : ( this.byId.get( to ) || {} ).name;
      Dom.toast( I18n.get( "batches.moved_done" ).replace( "{n}" , out.moved ).replace( "{name}" , name || "" ) );
    } catch ( error ) {
      App.showError( error.message );
    }
    await Batches.refresh( true );
  },

  async reorder( f , siblings , step ) {
    const ids = siblings.map( ( x ) => x.id );
    const at = ids.indexOf( f.id );
    ids.splice( at , 1 );
    ids.splice( at + step , 0 , f.id );
    try {
      await Api.post( "/api/ais/folders/order" , { parent_id: this.byId.has( f.parent_id ) ? f.parent_id : null , ids: ids } );
    } catch ( error ) {
      App.showError( error.message );
    }
    await Batches.refresh( true );
  },

  async remove( f ) {
    const parent = this.byId.has( f.parent_id ) ? f.parent_id : null;
    const parentName = parent == null ? I18n.get( "batches.folders_top" ) : this.byId.get( parent ).name;
    const question = I18n.get( "batches.folder_delete_confirm" ).replace( "{name}" , f.name ).replace( "{parent}" , parentName );
    if ( !( await Dom.confirm( question ) ) ) return;
    // Standing in it: go up to where its contents land.
    const here = this.current();
    const remove = async () => ( await Api.post( "/api/ais/folders/" + f.id + "/delete" , {} ) ).trash_id;
    let trashId;
    try {
      trashId = await remove();
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    if ( here === f.id ) this.go( parent );
    await Batches.refresh( true );
    // Undo (trash.js) files the folder and what it held back.
    Trash.undoable( I18n.get( "undo.deleted_folder" ) , trashId , remove , () => Batches.refresh( true ) );
  },
};
