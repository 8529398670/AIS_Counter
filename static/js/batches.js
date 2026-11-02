// The Batches screen: every batch the team shares (app/models/ais.py), one
// card each, to create, rename, add images to, open, assign, archive, export
// or delete, and to watch: files on the server, images completed (per
// assignee too), auto runs going on in anyone's browser, and per image on
// request. While the screen shows (and the tab is visible) it fetches the
// list again every few seconds, so it is the team's live monitor.
//
// The cards are in the team's priority order; admins change it by dragging a
// card's grip or from its menu. Reports (one batch, or every batch shown) are
// built in AisExport: an Excel workbook, or a ZIP with it and the traced PNGs.
//
// Images added here upload from this browser in the background, one file at
// a time, whichever screen is showing; Ais (ais.js) borrows those files
// (fileFor) when it needs one before its turn, and hears of each one that
// lands (Ais.fileStored), as the batch it loaded may predate the upload.
const Batches = {
  list: null,
  me: null,
  pollMs: 5000,
  expanded: new Set(),   // batch ids whose image list is open
  statuses: new Map(),   // batch id -> [{key, cell, files, stored, ais, auto, done, dup_of, assignee_name}]
  local: new Map(),      // batch id -> { reading, done, total } for this browser's adds and uploads
  files: new Map(),      // sha -> File picked here (kept after it uploads: Ais may still ask)
  queue: [],             // [{ batchId, sha }] waiting to upload
  editing: null,         // the batch id being renamed
  dragging: null,        // the batch id being dragged to a new place
  exports: new Map(),    // batch id -> progress text of an export from here
  addTarget: null,       // the batch the file pickers add to
  pendingNew: null,      // or the name of a batch to create once files are picked
  openAfter: null,       // a new batch's id: opened on Process once its images are added
  resetting: null,       // the batch the Reset results dialog is for
  pumping: false,

  init( me ) {
    this.me = me;
    Dom.get( "batches-new" ).addEventListener( "click" , () => this.showNew( true ) );
    Dom.get( "batches-new-cancel" ).addEventListener( "click" , () => this.showNew( false ) );
    Dom.get( "batches-new-form" ).addEventListener( "submit" , ( e ) => { e.preventDefault(); this.create(); } );
    Dom.all( "[data-new-add]" ).forEach( ( button ) => button.addEventListener( "click" ,
      () => this.createWith( button.getAttribute( "data-new-add" ) ) ) );
    Dom.get( "batches-mine" ).addEventListener( "change" , () => this.render() );
    Dom.get( "batches-archived" ).addEventListener( "change" , () => this.render() );
    Dom.all( "[data-export-all]" ).forEach( ( button ) => button.addEventListener( "click" ,
      () => this.exportAll( button.getAttribute( "data-export-all" ) ) ) );
    Dom.get( "batches-filter" ).addEventListener( "input" , () => this.render() );
    [ "batches-add-folder" , "batches-add-files" ].forEach( ( id ) => {
      const input = Dom.get( id );
      input.addEventListener( "change" , () => {
        const target = this.addTarget;
        const name = this.pendingNew;
        const picked = input.files;
        this.pendingNew = null;
        if ( picked && picked.length ) {
          if ( target ) this.addPicked( target , picked );
          else if ( name ) this.createPicked( name , picked );
        }
        input.value = "";
      } );
    } );
    // A poll does not redraw under an open menu; it catches up once it closes.
    Dom.get( "batches-list" ).addEventListener( "hidden.bs.dropdown" , () => this.render() );
    window.addEventListener( "hashchange" , () => this.onView() );
    document.addEventListener( "visibilitychange" , () => this.onView() );
    this.initReset();
    this.onView();
  },

  showing() {
    return Nav.current() === "batches";
  },

  // Poll while the screen shows and the tab is visible; stop otherwise.
  onView() {
    window.clearInterval( this.timer );
    this.timer = null;
    if ( !this.showing() || document.visibilityState !== "visible" ) return;
    this.refresh( this.list !== null );
    this.timer = window.setInterval( () => this.refresh( true ) , this.pollMs );
  },

  async refresh( quiet ) {
    try {
      this.list = ( await Api.request( "/api/ais/batches" ) ).batches;
    } catch ( error ) {
      if ( !quiet ) App.showError( error.message );
      return;
    }
    // The open image lists follow along too.
    await Promise.all( Array.from( this.expanded ).map( ( id ) => this.loadStatus( id ) ) );
    // Not under a name being typed, a card being dragged or an open menu
    // (that one catches up when it closes).
    if ( this.editing || this.dragging || document.querySelector( "#batches-panel .dropdown-menu.show" ) ) return;
    this.render();
  },

  async loadStatus( id ) {
    try {
      this.statuses.set( id , ( await Api.request( "/api/ais/batches/" + id + "/status" ) ).images );
    } catch ( error ) {
      if ( error.status === 404 ) this.expanded.delete( id );
    }
  },

  // --- creating and changing ---------------------------------------------------

  showNew( visible ) {
    const form = Dom.get( "batches-new-form" );
    Dom.show( form , visible );
    Dom.show( Dom.get( "batches-new-path" ) , Boolean( Ais.local && Ais.local.enabled ) );
    if ( visible ) {
      Dom.get( "batches-new-name" ).value = "";
      Dom.get( "batches-new-name" ).focus();
    }
  },

  // Create empty: the batch alone, to add images to later.
  async create() {
    const name = Dom.get( "batches-new-name" ).value.trim();
    if ( !name ) return;
    if ( await this.createNamed( name ) ) await this.refresh();
  },

  // The new batch, or null (the error shown).
  async createNamed( name ) {
    let batch;
    try {
      batch = await Api.post( "/api/ais/batches" , { name: name } );
    } catch ( error ) {
      App.showError( error.message );
      return null;
    }
    this.showNew( false );
    Dom.toast( I18n.get( "batches.created" ).replace( "{name}" , batch.name ) );
    this.fresh = batch.id;
    return batch;
  },

  // Folder… / Files… / Folder on this machine… on the new-batch form: the
  // picker opens in the click itself (a browser opens one only then), and
  // the batch is created once something is picked. Its images added, it
  // opens on the Process screen with the Images dialog.
  async createWith( how ) {
    const input = Dom.get( "batches-new-name" );
    const name = input.value.trim();
    if ( !name ) {
      input.reportValidity();
      return;
    }
    if ( how === "path" ) {
      const batch = await this.createNamed( name );
      if ( !batch ) return;
      this.openAfter = batch.id;
      await this.refresh( true );
      AisImages.openPathDialog( batch );
      return;
    }
    this.addTarget = null;
    this.pendingNew = name;
    Dom.get( how ).click();
  },

  async createPicked( name , fileList ) {
    const batch = await this.createNamed( name );
    if ( !batch ) return;
    this.openAfter = batch.id;
    await this.addPicked( batch , fileList );
  },

  // A batch created with its images: on to the Process screen, which shows
  // the Images dialog for it (Ais.followUrl).
  openNew( batch ) {
    if ( this.openAfter !== batch.id ) return;
    this.openAfter = null;
    Ais.openFresh = batch.id;
    window.location.hash = Ais.urlFor( batch , null );
  },

  startRename( b ) {
    this.editing = b.id;
    this.render();
    const input = Dom.get( "batches-rename-" + b.id );
    if ( input ) { input.focus(); input.select(); }
  },

  async rename( b , name ) {
    this.editing = null;
    name = name.trim();
    if ( !name || name === b.name ) {
      this.render();
      return;
    }
    try {
      const batch = await Api.post( "/api/ais/batches/" + b.id + "/rename" , { name: name } );
      Ais.batchChanged( batch , false );
    } catch ( error ) {
      App.showError( error.message );
    }
    await this.refresh( true );
  },

  async remove( b ) {
    const question = I18n.get( "ais.batch_delete_confirm" ).replace( "{name}" , b.name );
    if ( question && !window.confirm( question ) ) return;
    try {
      await Api.post( "/api/ais/batches/" + b.id + "/delete" , {} );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    if ( Ais.batch && Ais.batch.id === b.id ) Ais.closeBatch();
    this.queue = this.queue.filter( ( item ) => item.batchId !== b.id );
    this.local.delete( b.id );
    this.expanded.delete( b.id );
    await this.refresh( true );
  },

  async setArchived( b , archived ) {
    try {
      await Api.post( "/api/ais/batches/" + b.id + "/archive" , { archived: archived } );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    Dom.toast( I18n.get( archived ? "batches.archived_done" : "batches.unarchived_done" ).replace( "{name}" , b.name ) );
    await this.refresh( true );
  },

  // --- resetting results (admins) ---------------------------------------------

  // Reset results deletes a batch's AIS (all, or auto mode's only) so it can
  // be run again; the dialog offers the ZIP export as a backup first and
  // resets only after it, or with "Reset without a backup" ticked.
  initReset() {
    this.resetModal = bootstrap.Modal.getOrCreateInstance( Dom.get( "batches-reset-modal" ) );
    this.backedUp = false;
    Dom.get( "batches-reset-backup" ).addEventListener( "click" , () => this.backup() );
    Dom.get( "batches-reset-skip" ).addEventListener( "change" , () => this.renderReset() );
    Dom.get( "batches-reset-go" ).addEventListener( "click" , () => this.reset() );
  },

  openReset( b ) {
    this.resetting = b;
    this.backedUp = false;
    Dom.text( Dom.get( "batches-reset-batch" ) , b.name );
    Dom.text( Dom.get( "batches-reset-all-label" ) , I18n.get( "batches.reset_all" ).replace( "{n}" , b.ais ) );
    Dom.text( Dom.get( "batches-reset-auto-label" ) , I18n.get( "batches.reset_auto" ).replace( "{n}" , b.auto || 0 ) );
    Dom.get( "batches-reset-all" ).checked = true;
    Dom.get( "batches-reset-auto" ).disabled = !b.auto;
    Dom.get( "batches-reset-skip" ).checked = false;
    Dom.text( Dom.get( "batches-reset-backup-status" ) , "" );
    this.renderReset();
    this.resetModal.show();
  },

  renderReset() {
    Dom.get( "batches-reset-go" ).disabled = !this.resetting || this.resetBusy ||
      !( this.backedUp || Dom.get( "batches-reset-skip" ).checked );
    Dom.get( "batches-reset-backup" ).disabled = Boolean( this.resetBusy );
  },

  async backup() {
    const b = this.resetting;
    if ( !b ) return;
    const status = Dom.get( "batches-reset-backup-status" );
    this.resetBusy = true;
    this.renderReset();
    Dom.text( status , I18n.get( "batches.reset_backing_up" ) );
    try {
      const items = await this.gather( [ b ] );
      await AisExport.exportReport( items , b.name , "zip" , ( done , total ) => Dom.text( status ,
        total ? I18n.get( "batches.exporting" ).replace( "{done}" , done ).replace( "{total}" , total ) : "" ) );
      this.backedUp = true;
      Dom.text( status , I18n.get( "batches.reset_backed_up" ) );
    } catch ( error ) {
      Dom.text( status , "" );
      App.showError( error.message );
    }
    this.resetBusy = false;
    this.renderReset();
  },

  async reset() {
    const b = this.resetting;
    if ( !b ) return;
    const scope = Dom.get( "batches-reset-auto" ).checked ? "auto" : "all";
    this.resetBusy = true;
    this.renderReset();
    let out;
    try {
      out = await Api.post( "/api/ais/batches/" + b.id + "/reset" , { scope: scope } );
    } catch ( error ) {
      App.showError( error.message );
      return;
    } finally {
      this.resetBusy = false;
      this.renderReset();
    }
    this.resetting = null;
    this.resetModal.hide();
    Dom.toast( I18n.get( "batches.reset_done" ).replace( "{name}" , b.name ).replace( "{n}" , out.deleted ) );
    // The open batch reloads (its rows and done marks) when Process shows it.
    if ( Ais.batch && Ais.batch.id === b.id ) {
      AisAuto.reset();
      Ais.batchChanged( out.batch , true );
    }
    await this.refresh( true );
  },

  // --- the priority order (admins) ---------------------------------------------

  // Every batch id in order with id moved before (or after) the batch at, or
  // to the top when at is null. Batches hidden by the filters keep their place.
  moved( id , at , after ) {
    const ids = this.list.map( ( b ) => b.id ).filter( ( x ) => x !== id );
    const index = at == null ? 0 : ids.indexOf( at ) + ( after ? 1 : 0 );
    ids.splice( Math.max( 0 , index ) , 0 , id );
    return ids;
  },

  // Up or down past the next batch shown.
  move( b , step ) {
    const shown = this.shown();
    const next = shown[ shown.findIndex( ( x ) => x.id === b.id ) + step ];
    if ( next ) this.saveOrder( this.moved( b.id , next.id , step > 0 ) );
  },

  async saveOrder( ids ) {
    const byId = new Map( this.list.map( ( b ) => [ b.id , b ] ) );
    this.list = ids.map( ( id ) => byId.get( id ) ).filter( Boolean );
    this.render();
    try {
      await Api.post( "/api/ais/batches/order" , { ids: ids } );
    } catch ( error ) {
      App.showError( error.message );
    }
    await this.refresh( true );
  },

  // Dragging a card by its grip: the card under the pointer shows on which
  // side it would land (left / right with more than one column, else above /
  // below).
  dragHandlers( card , b ) {
    const sides = [ "batches-drop-before" , "batches-drop-after" , "batches-drop-vertical" ];
    const side = ( e ) => {
      const rect = card.getBoundingClientRect();
      const columns = window.getComputedStyle( Dom.get( "batches-list" ) ).gridTemplateColumns.split( " " ).length;
      return columns > 1 ? [ e.clientX > rect.left + rect.width / 2 , false ] : [ e.clientY > rect.top + rect.height / 2 , true ];
    };
    card.addEventListener( "dragstart" , ( e ) => {
      this.dragging = b.id;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData( "text/plain" , String( b.id ) );
      card.classList.add( "batches-dragging" );
    } );
    card.addEventListener( "dragend" , () => {
      card.draggable = false;
      card.classList.remove( "batches-dragging" );
      Dom.all( ".batches-card" ).forEach( ( c ) => c.classList.remove( ...sides ) );
      // A drop saves (and redraws); a drag let go elsewhere just ends.
      window.setTimeout( () => { this.dragging = null; } , 0 );
    } );
    card.addEventListener( "dragover" , ( e ) => {
      if ( this.dragging == null || this.dragging === b.id ) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const [ after , vertical ] = side( e );
      card.classList.toggle( "batches-drop-before" , !after );
      card.classList.toggle( "batches-drop-after" , after );
      card.classList.toggle( "batches-drop-vertical" , vertical );
    } );
    card.addEventListener( "dragleave" , ( e ) => {
      if ( !card.contains( e.relatedTarget ) ) card.classList.remove( ...sides );
    } );
    card.addEventListener( "drop" , ( e ) => {
      if ( this.dragging == null || this.dragging === b.id ) return;
      e.preventDefault();
      const id = this.dragging;
      this.dragging = null;
      this.saveOrder( this.moved( id , b.id , side( e )[ 0 ] ) );
    } );
  },

  // --- reports -------------------------------------------------------------------

  // [{ batch , images , rows }] for the batches given, fetched now. rows:
  // one batch's accepted AIS, or (several batches) all of them, split here.
  async gather( list ) {
    const one = list.length === 1;
    const results = ( await Api.request( "/api/ais/results?batch=" + ( one ? list[ 0 ].id : "all" ) ) ).results;
    const statuses = await Promise.all( list.map( ( b ) => Api.request( "/api/ais/batches/" + b.id + "/status" ).then( ( r ) => r.images ) ) );
    return list.map( ( b , i ) => ( { batch: b , images: statuses[ i ] , rows: results.filter( ( r ) => r.batch_id === b.id ) } ) );
  },

  async exportBatch( b , kind ) {
    const note = ( text ) => {
      if ( text ) this.exports.set( b.id , text );
      else this.exports.delete( b.id );
      this.renderExport( b.id );
    };
    note( I18n.get( "batches.preparing" ) );
    try {
      const items = await this.gather( [ b ] );
      await AisExport.exportReport( items , b.name , kind , ( done , total ) =>
        note( total ? I18n.get( "batches.exporting" ).replace( "{done}" , done ).replace( "{total}" , total ) : "" ) );
    } catch ( error ) {
      App.showError( error.message );
    }
    note( "" );
  },

  // Every batch the screen shows: the filter, Mine only and Show archived apply.
  async exportAll( kind ) {
    const line = Dom.get( "batches-export-status" );
    const note = ( text ) => {
      Dom.text( line , text );
      Dom.show( line , Boolean( text ) );
    };
    const list = this.list ? this.shown() : [];
    if ( !list.length ) {
      App.showError( I18n.get( "batches.nothing_to_export" ) );
      return;
    }
    note( I18n.get( "batches.preparing" ) );
    try {
      const items = await this.gather( list );
      await AisExport.exportReport( items , list.length === 1 ? list[ 0 ].name : "batches" , kind , ( done , total ) =>
        note( total ? I18n.get( "batches.exporting" ).replace( "{done}" , done ).replace( "{total}" , total ) : "" ) );
    } catch ( error ) {
      App.showError( error.message );
    }
    note( "" );
  },

  renderExport( id ) {
    const line = Dom.get( "batches-export-" + id );
    if ( !line ) return;
    Dom.text( line , this.exports.get( id ) || "" );
    Dom.show( line , this.exports.has( id ) );
  },

  pick( b , id ) {
    this.addTarget = b;
    this.pendingNew = null;
    Dom.get( id ).click();
  },

  // Files picked in this browser: hash them, add them to the batch, then
  // upload them in the background.
  async addPicked( b , fileList ) {
    const progress = { reading: true , done: 0 , total: 0 };
    this.local.set( b.id , progress );
    let picked;
    try {
      picked = await Ais.hashFiles( fileList , ( done , total ) => {
        progress.done = done;
        progress.total = total;
        this.renderLocal( b.id );
      } );
      if ( !picked ) {
        App.showError( I18n.get( "ais.no_tiffs" ) );
        this.local.delete( b.id );
        this.render();
        return;
      }
      const batch = await Api.post( "/api/ais/batches/" + b.id + "/upload" , { files: picked.files } );
      Ais.batchChanged( batch , true );
      Dom.toast( I18n.get( "batches.added" ).replace( "{n}" , picked.files.length ).replace( "{name}" , batch.name ) );
      // Only what the server does not have yet, each sha once.
      const waiting = new Set();
      batch.images.forEach( ( image ) => Object.values( image.files ).forEach( ( f ) => {
        if ( !f.stored ) waiting.add( f.sha );
      } ) );
      picked.files.forEach( ( f ) => {
        if ( waiting.has( f.sha ) && !this.queue.some( ( q ) => q.sha === f.sha ) ) {
          this.files.set( f.sha , picked.byRel.get( f.rel ) );
          this.queue.push( { batchId: b.id , sha: f.sha } );
        }
      } );
    } catch ( error ) {
      App.showError( error.message );
      this.local.delete( b.id );
      this.render();
      return;
    }
    this.local.delete( b.id );
    this.pump();
    await this.refresh( true );
    this.openNew( b );
  },

  // A folder on this machine (the Open path dialog), read by the server.
  async addPath( b , path ) {
    this.local.set( b.id , { reading: true , done: 0 , total: 0 } );
    this.render();
    try {
      const batch = await Api.post( "/api/ais/batches/" + b.id + "/path" , { path: path } );
      Ais.batchChanged( batch , true );
      Dom.toast( I18n.get( "batches.added_path" ).replace( "{name}" , batch.name ) );
    } catch ( error ) {
      App.showError( error.message );
      this.openAfter = null;
    }
    this.local.delete( b.id );
    await this.refresh( true );
    this.openNew( b );
  },

  // --- uploading ---------------------------------------------------------------

  fileFor( sha ) {
    return this.files.get( sha ) || null;
  },

  async pump() {
    if ( this.pumping ) return;
    this.pumping = true;
    try {
      while ( this.queue.length ) {
        const item = this.queue[ 0 ];
        const file = this.files.get( item.sha );
        const progress = this.local.get( item.batchId ) || { reading: false , done: 0 , total: 0 };
        if ( !this.local.has( item.batchId ) ) {
          progress.total = this.queue.filter( ( q ) => q.batchId === item.batchId ).length;
          this.local.set( item.batchId , progress );
        }
        this.renderLocal( item.batchId );
        if ( file ) {
          try {
            await Api.post( "/api/ais/files" , { data: await Ais.base64( file ) } );
          } catch ( error ) {
            App.showError( file.name + ": " + error.message );
            this.queue = this.queue.filter( ( q ) => q.batchId !== item.batchId );
            this.local.delete( item.batchId );
            continue;
          }
        }
        if ( file ) Ais.fileStored( item.sha );
        this.queue.shift();
        progress.done += 1;
        if ( !this.queue.some( ( q ) => q.batchId === item.batchId ) ) {
          this.local.delete( item.batchId );
          this.refresh( true );
        }
        this.renderLocal( item.batchId );
      }
    } finally {
      this.pumping = false;
    }
  },

  // --- the screen --------------------------------------------------------------

  admin() {
    return Boolean( this.me && this.me.role === "admin" );
  },

  mine( b ) {
    return Boolean( b.mine ) || Boolean( this.me && b.created_by === this.me.id );
  },

  // The batches the filters let through, in order.
  shown() {
    const filter = Dom.get( "batches-filter" ).value.trim().toLowerCase();
    const mineOnly = Dom.get( "batches-mine" ).checked;
    const archived = Dom.get( "batches-archived" ).checked;
    return this.list.filter( ( b ) => ( !mineOnly || this.mine( b ) ) && ( archived || !b.archived_at )
      && ( !filter || b.name.toLowerCase().includes( filter ) || ( b.path || "" ).toLowerCase().includes( filter ) ) );
  },

  render() {
    if ( !this.list ) return;
    const shown = this.shown();
    const holder = Dom.get( "batches-list" );
    Dom.clear( holder );
    Dom.show( Dom.get( "batches-none" ) , !shown.length );
    Dom.text( Dom.get( "batches-none" ) , I18n.get( this.list.length ? "batches.none_match" : "batches.none" ) );
    shown.forEach( ( b ) => holder.appendChild( this.card( b ) ) );
    if ( this.fresh ) {
      const card = Dom.get( "batches-card-" + this.fresh );
      if ( card ) {
        card.scrollIntoView( { block: "nearest" } );
        Dom.flash( card , 1500 );
      }
      this.fresh = null;
    }
  },

  // Just this browser's line on one card, between polls.
  renderLocal( id ) {
    const line = Dom.get( "batches-local-" + id );
    if ( line ) this.renderLocalInto( line , id );
  },

  bar( label , done , total , tone ) {
    const share = total ? 100 * done / total : 0;
    const full = total > 0 && done >= total;
    const bar = Dom.el( "div" , { class: "progress batches-bar" , attrs: {
      role: "progressbar" , "aria-label": label , "aria-valuenow": String( done ) , "aria-valuemin": "0" , "aria-valuemax": String( total ) ,
    } , children: [ Dom.el( "div" , { class: "progress-bar " + ( full ? "bg-success" : tone ) } ) ] } );
    bar.firstChild.style.width = share + "%";
    return Dom.el( "div" , { class: "batches-measure" , children: [
      Dom.el( "span" , { class: "small text-body-secondary" , text: label } ),
      bar,
      Dom.el( "span" , { class: "small text-nowrap" , text: done + " / " + total } ),
    ] } );
  },

  iconButton( icon , title , onClick , extra ) {
    return Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary" + ( extra ? " " + extra : "" ),
      attrs: { type: "button" , title: title , "aria-label": title },
      children: [ Dom.el( "i" , { class: "bi " + icon } ) ],
      on: { click: onClick },
    } );
  },

  title( b , canChange ) {
    if ( this.editing === b.id ) {
      const input = Dom.el( "input" , { class: "form-control form-control-sm" , attrs: {
        id: "batches-rename-" + b.id , value: b.name , maxlength: "200" , "aria-label": I18n.get( "batches.rename" ) ,
      } } );
      let done = false;
      const finish = ( save ) => {
        if ( done ) return;
        done = true;
        if ( save ) this.rename( b , input.value );
        else { this.editing = null; this.render(); }
      };
      input.addEventListener( "keydown" , ( e ) => {
        if ( e.key === "Enter" ) { e.preventDefault(); finish( true ); }
        if ( e.key === "Escape" ) { e.preventDefault(); finish( false ); }
      } );
      input.addEventListener( "blur" , () => finish( true ) );
      return input;
    }
    const children = [];
    if ( this.admin() ) children.push( Dom.el( "span" , {
      class: "batches-grip text-body-secondary",
      attrs: { title: I18n.get( "batches.drag" ) , "aria-hidden": "true" },
      children: [ Dom.el( "i" , { class: "bi bi-grip-vertical" } ) ],
      // Only the grip starts a drag, so text in the card can still be selected.
      on: { mousedown: ( e ) => { e.target.closest( ".batches-card" ).draggable = true; } ,
        mouseup: ( e ) => { e.target.closest( ".batches-card" ).draggable = false; } },
    } ) );
    children.push( Dom.el( "a" , { class: "fw-semibold text-truncate batches-name" , text: b.name ,
      attrs: { href: Ais.urlFor( b , null ) , title: I18n.get( "batches.open" ) } } ) );
    if ( b.archived_at ) children.push( Dom.badge( I18n.get( "batches.archived" ) , "secondary" ) );
    if ( canChange ) children.push( Dom.el( "button" , {
      class: "btn btn-sm btn-link p-0 text-body-secondary batches-rename",
      attrs: { type: "button" , title: I18n.get( "batches.rename" ) , "aria-label": I18n.get( "batches.rename" ) + ": " + b.name },
      children: [ Dom.el( "i" , { class: "bi bi-pencil" } ) ],
      on: { click: () => this.startRename( b ) },
    } ) );
    return Dom.el( "div" , { class: "d-flex align-items-center gap-2 min-w-0" , children: children } );
  },

  menuItem( icon , label , onClick , extra ) {
    return Dom.el( "li" , { children: [ Dom.el( "button" , {
      class: "dropdown-item" + ( extra ? " " + extra : "" ) , attrs: { type: "button" } , on: { click: onClick },
      children: [ Dom.el( "i" , { class: "bi " + icon + " me-2" } ) , Dom.el( "span" , { text: label } ) ],
    } ) ] } );
  },

  dropdown( button , items , end ) {
    return Dom.el( "div" , { class: "btn-group" , children: [ button ,
      Dom.el( "ul" , { class: "dropdown-menu" + ( end ? " dropdown-menu-end" : "" ) , children: items } ) ] } );
  },

  exportMenu( b ) {
    return this.dropdown( Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary dropdown-toggle",
      attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , title: I18n.get( "batches.export" ) },
      children: [ Dom.el( "i" , { class: "bi bi-download" } ) ],
    } ) , [
      this.menuItem( "bi-file-earmark-spreadsheet" , I18n.get( "batches.export_xlsx" ) , () => this.exportBatch( b , "xlsx" ) ),
      this.menuItem( "bi-file-earmark-zip" , I18n.get( "batches.export_zip" ) , () => this.exportBatch( b , "zip" ) ),
    ] , true );
  },

  // Rename, priority and reset results (admins), archive and delete.
  moreMenu( b , canChange ) {
    const items = [];
    const divider = () => Dom.el( "li" , { children: [ Dom.el( "hr" , { class: "dropdown-divider" } ) ] } );
    if ( canChange ) items.push( this.menuItem( "bi-pencil" , I18n.get( "batches.rename" ) , () => this.startRename( b ) ) );
    if ( this.admin() ) {
      if ( items.length ) items.push( divider() );
      items.push(
        this.menuItem( "bi-chevron-double-up" , I18n.get( "batches.move_top" ) , () => this.saveOrder( this.moved( b.id , null , false ) ) ),
        this.menuItem( "bi-chevron-up" , I18n.get( "batches.move_up" ) , () => this.move( b , -1 ) ),
        this.menuItem( "bi-chevron-down" , I18n.get( "batches.move_down" ) , () => this.move( b , 1 ) ),
      );
      if ( b.ais ) {
        items.push( divider() );
        items.push( this.menuItem( "bi-arrow-counterclockwise" , I18n.get( "batches.reset" ) , () => this.openReset( b ) , "text-danger" ) );
      }
    }
    if ( canChange ) {
      items.push( divider() );
      items.push( b.archived_at
        ? this.menuItem( "bi-box-arrow-up" , I18n.get( "batches.unarchive" ) , () => this.setArchived( b , false ) )
        : this.menuItem( "bi-archive" , I18n.get( "batches.archive" ) , () => this.setArchived( b , true ) ) );
      items.push( this.menuItem( "bi-trash" , I18n.get( "batches.delete" ) , () => this.remove( b ) , "text-danger" ) );
    }
    if ( !items.length ) return null;
    return this.dropdown( Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary",
      attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , title: I18n.get( "batches.more" ) , "aria-label": I18n.get( "batches.more" ) },
      children: [ Dom.el( "i" , { class: "bi bi-three-dots" } ) ],
    } ) , items , true );
  },

  addMenu( b ) {
    const item = ( icon , key , onClick ) => Dom.el( "li" , { children: [ Dom.el( "button" , {
      class: "dropdown-item" , attrs: { type: "button" } , on: { click: onClick },
      children: [ Dom.el( "i" , { class: "bi " + icon + " me-2" } ) , Dom.el( "span" , { text: I18n.get( key ) } ) ],
    } ) ] } );
    const items = [
      item( "bi-folder2-open" , "batches.add_folder" , () => this.pick( b , "batches-add-folder" ) ),
      item( "bi-images" , "batches.add_files" , () => this.pick( b , "batches-add-files" ) ),
    ];
    if ( Ais.local && Ais.local.enabled ) items.push( item( "bi-hdd" , "batches.add_path" , () => AisImages.openPathDialog( b ) ) );
    const empty = b.images === 0;
    return Dom.el( "div" , { class: "btn-group" , children: [
      Dom.el( "button" , {
        class: "btn btn-sm dropdown-toggle " + ( empty ? "btn-primary" : "btn-outline-primary" ),
        attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" },
        children: [ Dom.el( "i" , { class: "bi bi-plus-lg me-1" } ) , Dom.el( "span" , { text: I18n.get( "batches.add" ) } ) ],
      } ),
      Dom.el( "ul" , { class: "dropdown-menu" , children: items } ),
    ] } );
  },

  card( b ) {
    const admin = this.admin();
    const canChange = admin || Boolean( this.me && b.created_by === this.me.id );
    const expanded = this.expanded.has( b.id );
    const source = b.source === "path" || b.source === "mixed" ? ( b.path || "" ) : I18n.get( "ais.uploaded" );
    const meta = [ source , I18n.get( "batches.by" ).replace( "{name}" , b.created_by_name || "?" ) ,
      new Date( b.created_at ).toLocaleString() ];
    if ( b.updated_at && b.updated_at !== b.created_at ) meta.push( I18n.get( "batches.updated" ).replace( "{ago}" , this.ago( b.updated_at ) ) );

    const actions = [ this.addMenu( b ) ];
    if ( b.images ) actions.push( Dom.el( "a" , { class: "btn btn-sm btn-outline-secondary" , attrs: { href: Ais.urlFor( b , null ) } ,
      children: [ Dom.el( "i" , { class: "bi bi-box-arrow-in-right me-1" } ) , Dom.el( "span" , { text: I18n.get( "batches.open" ) } ) ] } ) );
    if ( admin && b.images ) actions.push( this.iconButton( "bi-people" , I18n.get( "ais.assign" ) , () => AisAssign.open( b ) ) );
    if ( b.images ) actions.push( this.exportMenu( b ) );
    const more = this.moreMenu( b , canChange );
    if ( more ) actions.push( more );

    const body = [
      Dom.el( "div" , { class: "batches-head" , children: [
        Dom.el( "div" , { class: "min-w-0" , children: [
          this.title( b , canChange ),
          Dom.el( "div" , { class: "small text-body-secondary text-truncate" , text: meta.filter( Boolean ).join( " · " ) , attrs: { title: b.path || "" } } ),
        ] } ),
        Dom.el( "div" , { class: "batches-actions" , children: actions } ),
      ] } ),
    ];

    if ( !b.images && !this.local.has( b.id ) ) {
      body.push( Dom.el( "p" , { class: "small text-body-secondary mb-0 mt-2" , text: I18n.get( "batches.empty" ) } ) );
    } else {
      const counts = [ I18n.get( "ais.n_ais" ).replace( "{n}" , b.ais || 0 ) ];
      if ( b.duplicates ) counts.push( I18n.get( "batches.n_duplicates" ).replace( "{n}" , b.duplicates ) );
      body.push( Dom.el( "div" , { class: "batches-measures" , children: [
        this.bar( I18n.get( "batches.on_server" ) , b.stored ?? b.files , b.files , "bg-info" ),
        this.bar( I18n.get( "batches.completed" ) , b.completed , b.images , "" ),
        Dom.el( "div" , { class: "small text-body-secondary" , text: counts.join( " · " ) } ),
      ] } ) );
    }

    const local = Dom.el( "div" , { class: "small text-primary mt-1" , attrs: { id: "batches-local-" + b.id } } );
    body.push( local );
    const exporting = Dom.el( "div" , { class: "small text-primary mt-1" , attrs: { id: "batches-export-" + b.id } ,
      text: this.exports.get( b.id ) || "" } );
    Dom.show( exporting , this.exports.has( b.id ) );
    body.push( exporting );

    ( b.activity || [] ).forEach( ( a ) => body.push( Dom.el( "div" , { class: "small mt-1 batches-activity" , children: [
      Dom.el( "i" , { class: "bi bi-magic me-1" + ( a.state === "running" ? " text-primary" : " text-body-secondary" ) } ),
      Dom.el( "span" , { text: I18n.get( "batches.auto_" + a.state ).replace( "{name}" , a.name || "?" )
        .replace( "{done}" , a.done ).replace( "{total}" , a.total ) } ),
    ] } ) ) );

    if ( b.assignees.length ) {
      body.push( Dom.el( "div" , { class: "ais-assignees mt-2" , children: this.assigneeLines( b ) } ) );
    }

    if ( b.images ) {
      body.push( Dom.el( "button" , {
        class: "btn btn-sm btn-link px-0 mt-1",
        attrs: { type: "button" , "aria-expanded": String( expanded ) },
        children: [ Dom.el( "i" , { class: "bi " + ( expanded ? "bi-chevron-down" : "bi-chevron-right" ) + " me-1" } ) ,
          Dom.el( "span" , { text: I18n.get( expanded ? "batches.hide_images" : "batches.show_images" ).replace( "{n}" , b.images ) } ) ],
        on: { click: () => this.toggle( b ) },
      } ) );
      if ( expanded ) body.push( this.statusTable( b ) );
    }

    const card = Dom.el( "div" , { class: "card batches-card" + ( this.mine( b ) ? " batches-card-mine" : "" )
      + ( b.archived_at ? " batches-card-archived" : "" ) ,
      attrs: { id: "batches-card-" + b.id } , children: [ Dom.el( "div" , { class: "card-body" , children: body } ) ] } );
    this.renderLocalInto( local , b.id );
    if ( admin ) this.dragHandlers( card , b );
    return card;
  },

  renderLocalInto( line , id ) {
    const p = this.local.get( id );
    Dom.text( line , p ? I18n.get( p.reading ? "batches.reading" : "batches.uploading" )
      .replace( "{done}" , p.done ).replace( "{total}" , p.total ) : "" );
    Dom.show( line , Boolean( p ) );
  },

  async toggle( b ) {
    if ( this.expanded.has( b.id ) ) {
      this.expanded.delete( b.id );
    } else {
      this.expanded.add( b.id );
      await this.loadStatus( b.id );
    }
    this.render();
  },

  // "5 min ago" for an ISO time.
  ago( iso ) {
    const seconds = Math.max( 0 , ( Date.now() - new Date( iso ).getTime() ) / 1000 );
    const [ n , unit ] = seconds < 60 ? [ 0 , "now" ] : seconds < 3600 ? [ Math.floor( seconds / 60 ) , "min" ]
      : seconds < 86400 ? [ Math.floor( seconds / 3600 ) , "h" ] : [ Math.floor( seconds / 86400 ) , "d" ];
    return I18n.get( "ais.ago_" + unit ).replace( "{n}" , n );
  },

  // One line per assignee: name, bar, completed / images, AIS, last activity.
  assigneeLines( b ) {
    return b.assignees.map( ( a ) => {
      const me = this.me && a.user_id === this.me.id;
      const share = a.images ? 100 * a.completed / a.images : 0;
      const bar = Dom.el( "div" , { class: "progress ais-assignee-bar" , attrs: {
        role: "progressbar" , "aria-label": a.name , "aria-valuenow": String( a.completed ) , "aria-valuemin": "0" , "aria-valuemax": String( a.images ) ,
      } , children: [ Dom.el( "div" , { class: "progress-bar" + ( a.images && a.completed === a.images ? " bg-success" : "" ) } ) ] } );
      bar.firstChild.style.width = share + "%";
      const details = [ a.completed + " / " + a.images , I18n.get( "ais.n_ais" ).replace( "{n}" , a.ais ) ];
      if ( a.last_at ) details.push( this.ago( a.last_at ) );
      return Dom.el( "div" , { class: "ais-assignee" + ( me ? " ais-assignee-me" : "" ) , children: [
        Dom.el( "span" , { class: "ais-assignee-name text-truncate" , text: a.name , attrs: { title: a.name + " · " + Math.round( a.percent ) + " %" } } ),
        bar,
        Dom.el( "span" , { class: "text-body-secondary text-nowrap" , text: details.join( " · " ) } ),
      ] } );
    } );
  },

  // One image's state, most telling first (the reports use it too).
  state( image ) {
    return AisExport.imageState( image );
  },

  statusTable( b ) {
    const images = this.statuses.get( b.id );
    if ( !images ) return Dom.el( "p" , { class: "small text-body-secondary" , text: "…" } );
    const tally = {};
    const rows = images.map( ( image ) => {
      const [ state , tone ] = this.state( image );
      tally[ state ] = ( tally[ state ] || 0 ) + 1;
      return Dom.el( "tr" , { children: [
        Dom.el( "td" , { children: [ Dom.el( "a" , { text: image.key , attrs: { href: Ais.urlFor( b , image ) } } ) ] } ),
        Dom.el( "td" , { children: [ Dom.badge( I18n.get( "batches.state_" + state ) , tone ) ] } ),
        Dom.el( "td" , { class: "text-nowrap" , text: image.ais ? I18n.get( "ais.n_ais" ).replace( "{n}" , image.ais ) : "" } ),
        Dom.el( "td" , { class: "text-truncate" , text: image.assignee_name || "" } ),
      ] } );
    } );
    const summary = Object.entries( tally ).map( ( [ state , n ] ) => n + " " + I18n.get( "batches.state_" + state ).toLowerCase() );
    return Dom.el( "div" , { class: "batches-status" , children: [
      Dom.el( "div" , { class: "small text-body-secondary mb-1" , text: summary.join( " · " ) } ),
      Dom.el( "div" , { class: "table-responsive batches-status-scroll" , children: [
        Dom.el( "table" , { class: "table table-sm align-middle small mb-0" , children: [
          Dom.el( "thead" , { children: [ Dom.el( "tr" , { children: [
            Dom.el( "th" , { text: I18n.get( "batches.col_image" ) } ),
            Dom.el( "th" , { text: I18n.get( "batches.col_state" ) } ),
            Dom.el( "th" , { text: I18n.get( "batches.col_ais" ) } ),
            Dom.el( "th" , { text: I18n.get( "batches.col_assignee" ) } ),
          ] } ) ] } ),
          Dom.el( "tbody" , { children: rows } ),
        ] } ),
      ] } ),
    ] } );
  },
};
