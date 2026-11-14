// The Batches screen: every batch the team shares (app/models/ais.py), one
// card each, to create, rename, add images to, open, assign, archive, export
// or delete, and to watch: files on the server, images completed (per
// assignee too), auto runs going on in anyone's browser, and per image on
// request. While the screen shows (and the tab is visible) it fetches the
// list again every few seconds, so it is the team's live monitor.
//
// The cards are in the team's priority order; admins change it by dragging a
// card's grip or from its menu. They are filed in the team's folders, which
// BatchFolders (batch_folders.js) lays out: one folder at a time or as a
// tree, as Settings says. Reports (one batch, or every batch shown) are
// built in AisExport: an Excel workbook, or a ZIP with it and the traced PNGs.
//
// Adding images blinds their names unless the Add menu's Randomize switch is
// off (app/models/ais.py), then opens the Images dialog on what came in; a
// card's Images button and folder chips open it at any time, to choose the
// images the team works on. ZIP exports ask what to put in (AisExport).
//
// Images added here upload from this browser in the background, a few files
// at a time, whichever screen is showing; Ais (ais.js) borrows those files
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
  resetting: null,       // the batch the Reset results dialog is for
  selected: new Set(),   // batch ids ticked for Compare selected (admins)
  pumping: 0,           // upload workers running
  randomizeKey: "batches-randomize",

  init( me ) {
    this.me = me;
    Dom.get( "batches-new" ).addEventListener( "click" , () => this.showNew( true ) );
    Dom.get( "batches-new-cancel" ).addEventListener( "click" , () => this.showNew( false ) );
    Dom.get( "batches-new-form" ).addEventListener( "submit" , ( e ) => { e.preventDefault(); this.create(); } );
    Dom.get( "batches-mine" ).addEventListener( "change" , () => this.render() );
    Dom.get( "batches-archived" ).addEventListener( "change" , () => this.render() );
    Dom.all( "[data-export-all]" ).forEach( ( button ) => button.addEventListener( "click" ,
      () => this.exportAll( button.getAttribute( "data-export-all" ) ) ) );
    this.initImport();
    Dom.get( "batches-filter" ).addEventListener( "input" , () => this.render() );
    [ "batches-add-folder" , "batches-add-files" ].forEach( ( id ) => {
      const input = Dom.get( id );
      input.addEventListener( "change" , () => {
        const target = this.addTarget;
        // A copy: input.files is live, and clearing the input below empties it.
        const picked = Array.from( input.files || [] );
        if ( target && picked.length ) {
          this.closeFolderAdd();
          this.addPicked( target , picked );
        }
        input.value = "";
      } );
    } );
    this.initFolderAdd();
    Dom.get( "batches-translation" ).addEventListener( "change" , ( e ) => {
      const file = e.target.files && e.target.files[ 0 ];
      if ( this.addTarget && file ) this.loadTranslation( this.addTarget , file );
      e.target.value = "";
    } );
    // A poll does not redraw under an open menu; it catches up once it closes.
    Dom.get( "batches-list" ).addEventListener( "hidden.bs.dropdown" , () => this.render() );
    // Another folder opened (#batches/folder/<id>) draws at once, then polls.
    window.addEventListener( "hashchange" , () => { if ( this.showing() ) this.render(); this.onView(); } );
    document.addEventListener( "visibilitychange" , () => this.onView() );
    this.initReset();
    Channels.init();
    Treatments.init();
    Compare.init();
    BatchFolders.init();
    Trash.init();
    Dom.get( "batches-compare" ).addEventListener( "click" , () => this.compareSelected() );
    this.onView();
  },

  // --- comparing batches by treatment (admins, compare.js) ---------------------

  // One culture per batch: the ticked ones still on the list, in its order.
  compareSelected() {
    this.compareList( ( this.list || [] ).filter( ( b ) => this.selected.has( b.id ) ) );
  },

  // Compare.run on list, its progress on the line above the cards (also a
  // folder's Compare, batch_folders.js).
  compareList( list ) {
    const line = Dom.get( "batches-export-status" );
    Compare.run( list , ( text ) => {
      Dom.text( line , text );
      Dom.show( line , Boolean( text ) );
    } );
  },

  renderCompare() {
    const button = Dom.get( "batches-compare" );
    const ids = new Set( ( this.list || [] ).map( ( b ) => b.id ) );
    [ ...this.selected ].forEach( ( id ) => { if ( !ids.has( id ) ) this.selected.delete( id ); } );
    Dom.show( button , this.admin() );
    button.disabled = this.selected.size < 2;
    Dom.text( Dom.get( "batches-compare-label" ) , I18n.get( "compare.button" ).replace( "{n}" , this.selected.size ) );
    const move = Dom.get( "batches-move-selected" );
    Dom.show( move , this.admin() && this.selected.size > 0 );
    Dom.text( Dom.get( "batches-move-selected-label" ) , I18n.get( "batches.move_selected" ).replace( "{n}" , this.selected.size ) );
  },

  selectBox( b ) {
    const box = Dom.el( "input" , { class: "form-check-input batches-select" ,
      attrs: { type: "checkbox" , title: I18n.get( "compare.select" ) , "aria-label": I18n.get( "compare.select" ) + ": " + b.name } } );
    box.checked = this.selected.has( b.id );
    box.addEventListener( "change" , () => {
      if ( box.checked ) this.selected.add( b.id );
      else this.selected.delete( b.id );
      this.renderCompare();
    } );
    return box;
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
    // A poll that started before a newer refresh must not draw its older list
    // over it (a batch just made would vanish until the next poll).
    const ask = this.asked = ( this.asked || 0 ) + 1;
    let reply;
    try {
      reply = await Api.request( "/api/ais/batches" );
    } catch ( error ) {
      if ( !quiet ) App.showError( error.message );
      return;
    }
    if ( ask !== this.asked ) return;
    BatchFolders.set( reply.folders );
    this.list = reply.batches;
    // The open image lists follow along too.
    await Promise.all( Array.from( this.expanded ).map( ( id ) => this.loadStatus( id ) ) );
    if ( ask !== this.asked ) return;
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
    if ( visible ) {
      Dom.get( "batches-new-name" ).value = "";
      Dom.get( "batches-new-name" ).focus();
    }
  },

  // The form's only way: a name and Enter make the batch, empty; its images
  // are added from its card (Add images).
  async create() {
    const name = Dom.get( "batches-new-name" ).value.trim();
    if ( !name ) return;
    if ( await this.createNamed( name ) ) await this.refresh();
  },

  // The new batch, or null (the error shown).
  async createNamed( name ) {
    let batch;
    try {
      // In the folder open, if one is.
      batch = await Api.post( "/api/ais/batches" , { name: name , folder_id: BatchFolders.here() } );
    } catch ( error ) {
      App.showError( error.message );
      return null;
    }
    this.showNew( false );
    Dom.toast( I18n.get( "batches.created" ).replace( "{name}" , batch.name ) );
    this.fresh = batch.id;
    return batch;
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

  // Into the trash (trash.js): the toast's Undo or the Trash dialog puts it back.
  async remove( b ) {
    const question = I18n.get( "ais.batch_delete_confirm" ).replace( "{name}" , b.name );
    if ( question && !window.confirm( question ) ) return;
    let trashId;
    try {
      trashId = await this.deleteBatch( b );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    await this.refresh( true );
    Trash.undoable( I18n.get( "undo.deleted_batch" ) , trashId , () => this.deleteBatch( b ) , () => this.refresh( true ) );
  },

  async deleteBatch( b ) {
    const out = await Api.post( "/api/ais/batches/" + b.id + "/delete" , {} );
    if ( Ais.batch && Ais.batch.id === b.id ) Ais.closeBatch();
    this.queue = this.queue.filter( ( item ) => item.batchId !== b.id );
    this.local.delete( b.id );
    this.expanded.delete( b.id );
    return out.trash_id;
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
      const items = await this.gather( [ b ] , true );
      // The images stay through a reset, so it can be imported back without them.
      await AisExport.exportReport( items , b.name , "zip" , ( done , total ) => Dom.text( status ,
        total ? I18n.get( "batches.exporting" ).replace( "{done}" , done ).replace( "{total}" , total ) : "" ) ,
      { traces: true , restorable: true , restorableFiles: false , grouped: false } );
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
    this.resetShown( b , out );
    await this.refresh( true );
    if ( out.trash_id ) {
      // Undo puts the results back from the trash; Redo resets again.
      const label = I18n.get( "undo.reset" ).replace( "{name}" , b.name ).replace( "{n}" , out.deleted );
      Trash.undoable( label , out.trash_id , async () => {
        const again = await Api.post( "/api/ais/batches/" + b.id + "/reset" , { scope: scope } );
        this.resetShown( b , again );
        return again.trash_id;
      } , () => Trash.changed( { kind: "reset" , batch_id: b.id } ) );
    } else {
      Dom.toast( I18n.get( "batches.reset_done" ).replace( "{name}" , b.name ).replace( "{n}" , out.deleted ) );
    }
  },

  // The open batch reloads (its rows and done marks) when Process shows it.
  resetShown( b , out ) {
    if ( Ais.batch && Ais.batch.id === b.id ) {
      AisAuto.reset();
      Ais.batchChanged( out.batch , true );
    }
  },

  // --- importing an export (admins) ----------------------------------------------

  initImport() {
    Dom.show( Dom.get( "batches-import" ) , this.admin() );
    Dom.get( "batches-import" ).addEventListener( "click" , () => Dom.get( "batches-import-file" ).click() );
    Dom.get( "batches-import-file" ).addEventListener( "change" , ( e ) => {
      const file = e.target.files && e.target.files[ 0 ];
      if ( file ) this.importBackup( file );
      e.target.value = "";
    } );
  },

  // The line above the list, for an import. It stays once done (what
  // happened), until the next one starts.
  statusLine( text ) {
    const line = Dom.get( "batches-export-status" );
    Dom.text( line , text );
    Dom.show( line , Boolean( text ) );
  },

  // A busy server answers 429: wait and go on, as AisExport.bytes does.
  async uploadPatiently( blob ) {
    for ( let tries = 0 ; ; tries += 1 ) {
      try {
        const info = await Api.postBytes( "/api/ais/files" , blob );
        if ( tries ) this.statusLine( "" );
        return info;
      } catch ( error ) {
        if ( error.status !== 429 || tries >= AisExport.retries ) throw error;
        this.statusLine( I18n.get( "batches.export_waiting" ) );
        await new Promise( ( resolve ) => window.setTimeout( resolve , 60000 ) );
      }
    }
  },

  // manifest.json of a backup ZIP, or null if it is anything else.
  async readBackup( file , entries ) {
    const entry = entries && entries.get( "manifest.json" );
    if ( !entry ) return null;
    let manifest;
    try {
      manifest = JSON.parse( await ( await Zip.blob( file , entry ) ).text() );
    } catch ( error ) {
      return null;
    }
    return manifest && manifest.format === "ais-batch-backup" && Array.isArray( manifest.batches ) ? manifest : null;
  },

  // The files first, a few at a time, then each batch: if anything fails no
  // half-made batch is left, only files in the store nothing uses yet. Names
  // in the ZIP are only looked up, never written anywhere.
  async importBackup( file ) {
    this.statusLine( I18n.get( "batches.import_reading" ) );
    try {
      const entries = await Zip.read( file );
      const manifest = await this.readBackup( file , entries );
      if ( !manifest ) throw new Error( I18n.get( "batches.import_not_backup" ) );
      const shas = new Set();
      manifest.batches.forEach( ( part ) => part.batch.images.forEach( ( image ) =>
        Ais.parts( image ).forEach( ( f ) => shas.add( f.sha ) ) ) );
      const { missing } = await Api.post( "/api/ais/batches/import/missing" , { shas: Array.from( shas ) } );
      const inZip = ( sha ) => entries.get( "files/" + sha + ".tif" ) || entries.get( "files/" + sha + ".czi" );
      const todo = missing.filter( inZip );
      let done = 0;
      const line = () => this.statusLine( I18n.get( "batches.import_uploading" ).replace( "{done}" , done ).replace( "{total}" , todo.length ) );
      line();
      const queue = todo.slice();
      const worker = async () => {
        while ( queue.length ) {
          const sha = queue.shift();
          const info = await this.uploadPatiently( await Zip.blob( file , inZip( sha ) ) );
          if ( info.sha256 !== sha ) throw new Error( I18n.get( "batches.import_wrong_file" ).replace( "{name}" , sha ) );
          Ais.fileStored( sha );
          done += 1;
          line();
        }
      };
      await Promise.all( Array.from( { length: Ais.concurrency } , worker ) );
      for ( let i = 0 ; i < manifest.batches.length ; i += 1 ) {
        this.statusLine( I18n.get( "batches.import_saving" ).replace( "{done}" , i + 1 ).replace( "{total}" , manifest.batches.length ) );
        const imported = await Api.post( "/api/ais/batches/import" , { format: manifest.format , version: manifest.version ,
          users: manifest.users , batch: manifest.batches[ i ].batch , results: manifest.batches[ i ].results ,
          measurements: manifest.batches[ i ].measurements } );
        // Into the folder open, as a new batch would be.
        if ( BatchFolders.here() != null ) await Api.post( "/api/ais/batches/move" , { ids: [ imported.id ] , folder_id: BatchFolders.here() } );
      }
      const absent = missing.length - todo.length;
      this.statusLine( I18n.get( "batches.import_done" ).replace( "{batches}" , manifest.batches.length ).replace( "{files}" , todo.length ) +
        ( absent ? " " + I18n.get( "batches.import_no_files" ).replace( "{n}" , absent ) : "" ) );
      this.refresh( true );
    } catch ( error ) {
      this.statusLine( "" );
      App.showError( error.message );
    }
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
      // Its own grid: in the tree view each folder has one.
      const columns = window.getComputedStyle( card.parentElement ).gridTemplateColumns.split( " " ).length;
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

  // [{ batch , images , rows , measurements }] for the batches given, fetched
  // now. rows: one batch's accepted AIS, or (several batches) all of them,
  // split here; measurements the same for its recorded lines.
  // Images the team left out, and their AIS, are not in it unless everything
  // is asked for (a backup).
  async gather( list , everything ) {
    const one = list.length === 1;
    const scope = one ? list[ 0 ].id : "all";
    const results = ( await Api.request( "/api/ais/results?batch=" + scope ) ).results;
    const lines = ( await Api.request( "/api/ais/measurements?batch=" + scope ) ).measurements;
    const statuses = await Promise.all( list.map( ( b ) => Api.request( "/api/ais/batches/" + b.id + "/status" ).then( ( r ) => r.images ) ) );
    return list.map( ( b , i ) => {
      const out = new Set( statuses[ i ].filter( ( image ) => !image.included && !everything ).map( ( image ) => image.key ) );
      return { batch: b , images: statuses[ i ].filter( ( image ) => !out.has( image.key ) ) ,
        rows: results.filter( ( r ) => r.batch_id === b.id && !out.has( r.image ) ) ,
        measurements: lines.filter( ( m ) => m.batch_id === b.id && !out.has( m.image ) ) };
    } );
  },

  exportLine( done , total , waiting ) {
    if ( waiting ) return I18n.get( "batches.export_waiting" );
    return total ? I18n.get( "batches.exporting" ).replace( "{done}" , done ).replace( "{total}" , total ) : "";
  },

  async exportBatch( b , kind , options ) {
    const note = ( text ) => {
      if ( text ) this.exports.set( b.id , text );
      else this.exports.delete( b.id );
      this.renderExport( b.id );
    };
    note( I18n.get( "batches.preparing" ) );
    try {
      const items = await this.gather( [ b ] );
      await AisExport.exportReport( items , b.name , kind , ( done , total , waiting ) =>
        note( this.exportLine( done , total , waiting ) ) , options );
    } catch ( error ) {
      App.showError( error.message );
    }
    note( "" );
  },

  // Every batch the screen shows: the filter, Mine only and Show archived
  // apply, and the folder open (with the folders inside it). A ZIP asks what
  // to put in first.
  exportAll( kind ) {
    const list = this.list ? BatchFolders.inView( this.shown() ) : [];
    if ( !list.length ) {
      App.showError( I18n.get( "batches.nothing_to_export" ) );
      return;
    }
    if ( kind === "zip" ) {
      AisExport.openOptions( list , list.length === 1 ? list[ 0 ].name : "batches" , ( options ) => this.exportShown( list , kind , options ) );
    } else {
      this.exportShown( list , kind );
    }
  },

  async exportShown( list , kind , options ) {
    const line = Dom.get( "batches-export-status" );
    const note = ( text ) => {
      Dom.text( line , text );
      Dom.show( line , Boolean( text ) );
    };
    note( I18n.get( "batches.preparing" ) );
    try {
      const items = await this.gather( list );
      await AisExport.exportReport( items , list.length === 1 ? list[ 0 ].name : "batches" , kind , ( done , total , waiting ) =>
        note( this.exportLine( done , total , waiting ) ) , options );
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
    Dom.get( id ).click();
  },

  // Folder…: a dialog with three ways in, as no one of them works in every
  // browser: drop the folder on it, choose the folder, or choose its files
  // (or a .zip of it).
  pickFolder( b ) {
    this.addTarget = b;
    Dom.get( "batches-addfolder-batch" ).textContent = b.name;
    bootstrap.Modal.getOrCreateInstance( Dom.get( "batches-addfolder-modal" ) ).show();
  },

  closeFolderAdd() {
    const element = Dom.get( "batches-addfolder-modal" );
    if ( element.classList.contains( "show" ) ) bootstrap.Modal.getOrCreateInstance( element ).hide();
  },

  initFolderAdd() {
    const zone = Dom.get( "batches-addfolder-drop" );
    const files = ( e ) => Array.from( e.dataTransfer?.types || [] ).includes( "Files" );
    zone.addEventListener( "dragover" , ( e ) => {
      if ( !files( e ) ) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      zone.classList.add( "is-over" );
    } );
    zone.addEventListener( "dragleave" , ( e ) => {
      if ( !zone.contains( e.relatedTarget ) ) zone.classList.remove( "is-over" );
    } );
    zone.addEventListener( "drop" , async ( e ) => {
      if ( !files( e ) ) return;
      e.preventDefault();
      zone.classList.remove( "is-over" );
      const target = this.addTarget;
      const picked = await this.droppedFiles( e.dataTransfer.items );
      if ( !target || !picked.length ) return;
      this.closeFolderAdd();
      this.addPicked( target , picked );
    } );
    // Straight from the click: a chooser needs its user activation.
    Dom.get( "batches-addfolder-choose" ).addEventListener( "click" , () => this.chooseFolder() );
    Dom.get( "batches-addfolder-files" ).addEventListener( "click" , () => Dom.get( "batches-add-files" ).click() );
  },

  // The browser's own folder chooser where it has one (Chrome, Edge: the
  // folder, subfolders and all), else the folder input.
  async chooseFolder() {
    const target = this.addTarget;
    if ( typeof window.showDirectoryPicker !== "function" ) {
      Dom.get( "batches-add-folder" ).click();
      return;
    }
    let folder;
    try {
      folder = await window.showDirectoryPicker( { id: "ais-images" , mode: "read" } );
    } catch ( error ) {
      if ( error.name !== "AbortError" ) App.showError( error.message );
      return;
    }
    const files = await this.filesIn( folder , folder.name );
    if ( !target ) return;
    this.closeFolderAdd();
    this.addPicked( target , files );
  },

  // Picked or dropped files with any .zip among them opened: its images (and
  // __Translation.txt) as files, each with its path in the ZIP. A ZIP whose
  // entries sit at its top level gets its own name as their folder.
  async expandZips( fileList , onOpen ) {
    const out = [];
    for ( const f of Array.from( fileList ) ) {
      if ( !/\.zip$/i.test( f.name ) ) {
        out.push( f );
        continue;
      }
      onOpen( f.name );
      const entries = await Zip.read( f );
      if ( !entries ) throw new Error( I18n.get( "batches.zip_bad" ).replace( "{name}" , f.name ) );
      const base = Ais.relPath( f ).split( "/" ).slice( 0 , -1 ).concat( f.name.replace( /\.zip$/i , "" ) ).join( "/" );
      const names = [ ...entries.keys() ].filter( ( name ) => !name.endsWith( "/" ) && !/(^|\/)(__MACOSX|\.)/.test( name )
        && /(\.(tiff?|czi)|^__Translation.*\.txt)$/i.test( name.split( "/" ).pop() ) );
      const nested = names.length && names.every( ( name ) => name.includes( "/" ) );
      for ( const name of names ) {
        const blob = await Zip.blob( f , entries.get( name ) );
        const file = new File( [ blob ] , name.split( "/" ).pop() , { lastModified: f.lastModified } );
        out.push( this.withPath( file , nested ? name : base + "/" + name ) );
      }
    }
    return out;
  },

  // Every file under a folder handle, each with its path from the folder.
  async filesIn( folder , path ) {
    const out = [];
    for await ( const entry of folder.values() ) {
      if ( entry.name.startsWith( "." ) ) continue;
      const rel = path + "/" + entry.name;
      if ( entry.kind === "directory" ) out.push( ...await this.filesIn( entry , rel ) );
      else out.push( this.withPath( await entry.getFile() , rel ) );
    }
    return out;
  },

  // Files (and folders, subfolders and all) dropped on a batch: every file
  // with its path from what was dropped. The entries are taken at once, as
  // a drop's items are gone once the handler returns.
  async droppedFiles( items ) {
    const entries = Array.from( items || [] ).map( ( item ) => item.webkitGetAsEntry && item.webkitGetAsEntry() ).filter( Boolean );
    const out = [];
    const walk = async ( entry , rel ) => {
      if ( entry.name.startsWith( "." ) ) return;
      if ( entry.isFile ) {
        out.push( this.withPath( await new Promise( ( ok , fail ) => entry.file( ok , fail ) ) , rel ) );
        return;
      }
      const reader = entry.createReader();
      for ( ;; ) {
        const some = await new Promise( ( ok , fail ) => reader.readEntries( ok , fail ) );
        if ( !some.length ) break;
        for ( const child of some ) await walk( child , rel + "/" + child.name );
      }
    };
    // A loose file dropped alone has no folder: its path is just "", as a picked file's.
    for ( const entry of entries ) await walk( entry , entry.isFile ? "" : entry.name );
    return out;
  },

  withPath( file , rel ) {
    Object.defineProperty( file , "aisRel" , { value: rel } );
    return file;
  },

  // Dropping files or folders from the computer on a batch's card adds them,
  // as Add images does.
  fileDrop( card , b ) {
    const files = ( e ) => Array.from( e.dataTransfer?.types || [] ).includes( "Files" );
    card.addEventListener( "dragover" , ( e ) => {
      if ( !files( e ) ) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      card.classList.add( "batches-file-over" );
    } );
    card.addEventListener( "dragleave" , ( e ) => {
      if ( !card.contains( e.relatedTarget ) ) card.classList.remove( "batches-file-over" );
    } );
    card.addEventListener( "drop" , async ( e ) => {
      if ( !files( e ) ) return;
      e.preventDefault();
      card.classList.remove( "batches-file-over" );
      const picked = await this.droppedFiles( e.dataTransfer.items );
      if ( picked.length ) this.addPicked( b , picked );
    } );
  },

  // Whether images added from here get blinded names: on unless switched
  // off in an Add menu, remembered in this browser.
  randomize() {
    try {
      return window.localStorage.getItem( this.randomizeKey ) !== "0";
    } catch ( error ) {
      return true;
    }
  },

  setRandomize( on ) {
    try {
      window.localStorage.setItem( this.randomizeKey , on ? "1" : "0" );
    } catch ( error ) { /* storage blocked: on for this visit */ }
  },

  // The newest add of a batch the server returned, to open the Images dialog on.
  lastAdd( batch ) {
    const adds = batch.adds || [];
    return adds.length ? adds[ adds.length - 1 ].id : null;
  },

  // A __Translation.txt for a batch blinded somewhere else and uploaded
  // without it (admins): the original names of the images it names.
  async loadTranslation( b , file ) {
    try {
      const out = await Api.post( "/api/ais/batches/" + b.id + "/translation" , { text: await file.text() } );
      Ais.batchChanged( out , true );
      Dom.toast( I18n.get( "batches.translation_loaded" ).replace( "{n}" , out.named ).replace( "{m}" , out.unnamed ) );
    } catch ( error ) {
      App.showError( error.message );
    }
    await this.refresh( true );
  },

  // --- channels and Z-stacks ---------------------------------------------------------

  // The Z-stacks among picked files, by name alone, as the server will find
  // them (app/models/ais.py _take_stacks): [{ cell , slices }].
  stacksIn( fileList ) {
    const found = new Map();
    Array.from( fileList ).forEach( ( f ) => {
      const match = f.name.startsWith( "." ) ? null : Ais.stackRe.exec( f.name );
      if ( !match ) return;
      const folder = Ais.relPath( f ).split( "/" ).slice( 0 , -1 ).join( "/" );
      const key = [ folder , match[ 1 ] , ( match[ 3 ] || "" ).toLowerCase() ].join( "\n" );
      found.set( key , { cell: match[ 1 ] , slices: ( found.has( key ) ? found.get( key ).slices : 0 ) + 1 } );
    } );
    return Array.from( found.values() ).filter( ( s ) => s.slices >= 2 );
  },

  // A folder on this machine: its channels and Z-stacks, asked about before
  // the server hashes anything (Channels.ask). null when the person backs out.
  async askAt( path ) {
    const [ found , { layouts } ] = await Promise.all( [ Api.post( "/api/ais/local/stacks" , { path: path } ) ,
      Api.post( "/api/ais/local/channels" , { path: path } ) ] );
    return Channels.ask( layouts , found.stacks , found.czi_stacks || [] );
  },

  // What an answer of Channels.ask adds to an add's body.
  addBody( asked ) {
    return Object.assign( {} , asked.channels.length ? { channels: asked.channels } : {} , asked.stack ? { stack: asked.stack } : {} ,
      asked.czi_stack ? { czi_stack: asked.czi_stack } : {} );
  },

  // Fill in the area (and Z-stack volume) of this batch's AIS saved without
  // one, a few at a time (POST fill-areas), its progress on the line above
  // the cards. An AIS whose new trace differs from its saved one is left as
  // it is, and counted.
  async fillAreas( b ) {
    if ( this.filling ) return;
    this.filling = true;
    const line = Dom.get( "batches-export-status" );
    const say = ( text ) => {
      Dom.text( line , text );
      Dom.show( line , Boolean( text ) );
    };
    let after = 0;
    let filled = 0;
    let failed = 0;
    try {
      for ( ;; ) {
        const out = await Api.post( "/api/ais/batches/" + b.id + "/fill-areas" , { after: after , limit: 10 } );
        filled += out.filled;
        failed += out.failed.length;
        after = out.after;
        say( I18n.get( "batches.fill_areas_progress" ).replace( "{name}" , b.name ).replace( "{done}" , filled + failed )
          .replace( "{total}" , filled + failed + out.remaining ) );
        if ( !out.remaining ) break;
      }
      say( "" );
      Dom.toast( I18n.get( filled + failed ? "batches.fill_areas_done" : "batches.fill_areas_none" )
        .replace( "{filled}" , filled ).replace( "{failed}" , failed ).replace( "{name}" , b.name ) );
      if ( Ais.batch && Ais.batch.id === b.id ) await Ais.loadBatchRows();
    } catch ( error ) {
      say( "" );
      App.showError( error.message );
    } finally {
      this.filling = false;
    }
  },

  async editChannels( b ) {
    try {
      if ( await Channels.edit( b.id , null ) ) await this.refresh( true );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // Files picked in this browser: hash them, add them to the batch, then
  // upload them in the background.
  async addPicked( b , fileList ) {
    const progress = { reading: true , done: 0 , total: 0 };
    this.local.set( b.id , progress );
    let picked;
    try {
      fileList = await this.expandZips( fileList , ( name ) => Dom.toast( I18n.get( "batches.zip_reading" ).replace( "{name}" , name ) ) );
      const stacks = this.stacksIn( fileList );
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
      // Which channel is the AIS (and the stacks' spacing), now the files
      // have been read; backing out adds nothing.
      const asked = await Channels.ask( picked.layouts , stacks , picked.cziStacks );
      if ( !asked ) {
        this.local.delete( b.id );
        this.render();
        return;
      }
      const batch = await Api.post( "/api/ais/batches/" + b.id + "/upload" , Object.assign( { files: picked.files ,
        randomize: this.randomize() , add_name: picked.name , translations: picked.translations } , this.addBody( asked ) ) );
      Ais.batchChanged( batch , true );
      Dom.toast( I18n.get( "batches.added" ).replace( "{n}" , picked.files.length ).replace( "{name}" , batch.name ) );
      // Only what the server does not have yet, each sha once.
      const waiting = new Set();
      batch.images.forEach( ( image ) => Ais.parts( image ).forEach( ( f ) => {
        if ( !f.stored ) waiting.add( f.sha );
      } ) );
      picked.files.forEach( ( f ) => {
        if ( waiting.has( f.sha ) && !this.queue.some( ( q ) => q.sha === f.sha ) ) {
          this.files.set( f.sha , picked.bySha.get( f.sha ) );
          this.queue.push( { batchId: b.id , sha: f.sha } );
        }
      } );
      this.local.delete( b.id );
      this.pump();
      AisImages.openBatch( batch , this.lastAdd( batch ) );
    } catch ( error ) {
      App.showError( error.message );
      this.local.delete( b.id );
      this.render();
      return;
    }
    await this.refresh( true );
  },

  // A folder on this machine (the Open path dialog), read by the server.
  async addPath( b , path ) {
    let asked;
    try {
      asked = await this.askAt( path );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    if ( !asked ) return;
    this.local.set( b.id , { reading: true , done: 0 , total: 0 } );
    this.render();
    try {
      const batch = await Api.post( "/api/ais/batches/" + b.id + "/path" , Object.assign( { path: path , randomize: this.randomize() } , this.addBody( asked ) ) );
      Ais.batchChanged( batch , true );
      Dom.toast( I18n.get( "batches.added_path" ).replace( "{name}" , batch.name ) );
      AisImages.openBatch( batch , this.lastAdd( batch ) );
    } catch ( error ) {
      App.showError( error.message );
    }
    this.local.delete( b.id );
    await this.refresh( true );
  },

  // --- uploading ---------------------------------------------------------------

  fileFor( sha ) {
    return this.files.get( sha ) || null;
  },

  // Up to Ais.concurrency uploads at once, each worker taking the next item.
  pump() {
    while ( this.pumping < Ais.concurrency && this.queue.length > this.pumping ) {
      this.pumping += 1;
      this.uploadNext().finally( () => { this.pumping -= 1; } );
    }
  },

  async uploadNext() {
    while ( this.queue.length ) {
      const item = this.queue.shift();
      // Not again if the Process screen has uploaded it meanwhile.
      const file = Ais.isStored( item.sha ) ? null : this.files.get( item.sha );
      let progress = this.local.get( item.batchId );
      if ( !progress ) {
        progress = { reading: false , done: 0 , total: 1 + this.queue.filter( ( q ) => q.batchId === item.batchId ).length };
        this.local.set( item.batchId , progress );
      }
      progress.active = ( progress.active || 0 ) + 1;
      this.renderLocal( item.batchId );
      if ( file ) {
        try {
          await this.uploadPatiently( file );
        } catch ( error ) {
          App.showError( file.name + ": " + error.message );
          this.queue = this.queue.filter( ( q ) => q.batchId !== item.batchId );
          this.local.delete( item.batchId );
          this.render();
          continue;
        }
        Ais.fileStored( item.sha );
      }
      progress.active -= 1;
      progress.done += 1;
      // The batch's last upload (none queued, none still going).
      if ( this.local.get( item.batchId ) === progress && !progress.active &&
        !this.queue.some( ( q ) => q.batchId === item.batchId ) ) {
        this.local.delete( item.batchId );
        this.refresh( true );
      }
      this.renderLocal( item.batchId );
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
    const any = BatchFolders.render( Dom.get( "batches-shelf" ) , holder , shown , ( b ) => this.card( b ) );
    Dom.show( Dom.get( "batches-none" ) , !any );
    Dom.text( Dom.get( "batches-none" ) , I18n.get( this.list.length ? "batches.none_match" : "batches.none" ) );
    this.renderCompare();
    if ( this.fresh ) {
      const card = Dom.get( "batches-card-" + this.fresh );
      if ( card ) {
        card.scrollIntoView( { block: "nearest" } );
        card.classList.add( "batches-card-fresh" );
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
        if ( Shortcuts.is( e , "batches.save_name" ) ) { e.preventDefault(); finish( true ); }
        else if ( Shortcuts.is( e , "batches.cancel_name" ) ) { e.preventDefault(); finish( false ); }
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
      this.menuItem( "bi-file-earmark-zip" , I18n.get( "batches.export_zip" ) , () => AisExport.openOptions( [ b ] , b.name ,
        ( options ) => this.exportBatch( b , "zip" , options ) ) ),
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
        this.menuItem( "bi-folder-symlink" , I18n.get( "batches.move_to_folder" ) , () => BatchFolders.openMove( { batchIds: [ b.id ] } ) ),
      );
      if ( b.images ) {
        items.push( divider() );
        items.push( this.menuItem( "bi-translate" , I18n.get( "batches.load_translation" ) , () => this.pick( b , "batches-translation" ) ) );
        items.push( this.menuItem( "bi-tags" , I18n.get( "treatments.menu" ) , () => this.reviewTreatments( b ) ) );
      }
      if ( b.ais ) {
        items.push( divider() );
        items.push( this.menuItem( "bi-arrow-counterclockwise" , I18n.get( "batches.reset" ) , () => this.openReset( b ) , "text-danger" ) );
      }
    }
    // Which channel is the AIS: whoever can add images to it.
    if ( ( canChange || this.admin() ) && b.images ) {
      if ( items.length ) items.push( divider() );
      items.push( this.menuItem( "bi-palette" , I18n.get( "channels.edit" ) , () => this.editChannels( b ) ) );
    }
    // AIS saved before area and volume were measured: trace them again for it.
    if ( b.ais ) items.push( this.menuItem( "bi-bounding-box" , I18n.get( "batches.fill_areas" ) , () => this.fillAreas( b ) ) );
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
    const id = "batches-randomize-" + b.id;
    const box = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , role: "switch" , id: id } ,
      on: { change: ( e ) => this.setRandomize( e.target.checked ) } } );
    box.checked = this.randomize();
    const items = [
      item( "bi-folder2-open" , "batches.add_folder" , () => this.pickFolder( b ) ),
      item( "bi-images" , "batches.add_files" , () => this.pick( b , "batches-add-files" ) ),
      Dom.el( "li" , { children: [ Dom.el( "hr" , { class: "dropdown-divider" } ) ] } ),
      // Its own click must not close the menu (Bootstrap closes on any click inside).
      Dom.el( "li" , { class: "px-3 py-1" , on: { click: ( e ) => e.stopPropagation() } , children: [
        Dom.el( "div" , { class: "form-check form-switch mb-0 small text-nowrap" , attrs: { title: I18n.get( "batches.randomize_hint" ) } , children: [
          box , Dom.el( "label" , { class: "form-check-label" , text: I18n.get( "batches.randomize" ) , attrs: { for: id } } ),
        ] } ),
      ] } ),
    ];
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
    if ( b.images ) actions.push( Dom.el( "button" , { class: "btn btn-sm btn-outline-secondary" ,
      attrs: { type: "button" , title: I18n.get( "batches.images_hint" ) } , on: { click: () => AisImages.openBatch( b , null ) } ,
      children: [ Dom.el( "i" , { class: "bi bi-grid-3x3-gap me-1" } ) ,
        Dom.el( "span" , { text: I18n.get( "batches.images_n" ).replace( "{n}" , this.includedOf( b ) ).replace( "{total}" , b.images ) } ) ] } ) );
    if ( admin && b.images ) actions.push( this.iconButton( "bi-people" , I18n.get( "ais.assign" ) , () => AisAssign.open( b ) ) );
    if ( b.images ) actions.push( this.exportMenu( b ) );
    const more = this.moreMenu( b , canChange );
    if ( more ) actions.push( more );

    const body = [
      Dom.el( "div" , { class: "batches-head" , children: [
        ...( admin && b.images ? [ this.selectBox( b ) ] : [] ),
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
        this.bar( I18n.get( "batches.completed" ) , b.completed , this.includedOf( b ) , "" ),
        Dom.el( "div" , { class: "small text-body-secondary" , text: counts.join( " · " ) } ),
      ] } ) );
    }

    if ( admin && b.unnamed ) {
      body.push( Dom.el( "div" , { class: "small text-warning-emphasis mt-1" , children: [
        Dom.el( "i" , { class: "bi bi-exclamation-triangle me-1" } ),
        Dom.el( "span" , { text: I18n.get( "batches.translation_missing" ).replace( "{n}" , b.unnamed ) + " " } ),
        Dom.el( "button" , { class: "btn btn-link btn-sm p-0 align-baseline" , attrs: { type: "button" } ,
          text: I18n.get( "batches.load_translation" ) , on: { click: () => this.pick( b , "batches-translation" ) } } ),
      ] } ) );
    }

    const folders = this.folderChips( b );
    if ( folders ) body.push( folders );
    const treatments = admin ? this.treatmentChips( b ) : null;
    if ( treatments ) body.push( treatments );

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
    this.fileDrop( card , b );
    return card;
  },

  includedOf( b ) {
    return b.included ?? b.images;
  },

  // One chip per folder (or set of files) added to the batch, each opening
  // the Images dialog on just those; "Earlier images" for what came in
  // before adds were recorded. Admins also get a menu on each to give its
  // images new random names (or random names at all).
  // Admins: the batch's saved treatments with their image counts (and how
  // many have none), each opening the Treatments dialog. Nothing until one
  // is saved.
  treatmentChips( b ) {
    const list = b.treatments || [];
    if ( !list.length ) return null;
    const review = () => this.reviewTreatments( b );
    const chip = ( text , cls , title ) => Dom.el( "button" , { class: "btn btn-sm border batches-treatment text-truncate " + cls ,
      attrs: { type: "button" , title: title } , on: { click: review } , text: text } );
    const chips = list.map( ( [ name , n ] ) => chip( name + " · " + n , "btn-light" , I18n.get( "batches.treatment_chip" ) ) );
    if ( b.untreated ) chips.push( chip( I18n.get( "batches.untreated" ).replace( "{n}" , b.untreated ) , "btn-outline-warning" ,
      I18n.get( "batches.untreated_hint" ) ) );
    return Dom.el( "div" , { class: "batches-folders batches-treatments mt-1" , children: [
      Dom.el( "i" , { class: "bi bi-tags text-body-secondary align-self-center" , attrs: { title: I18n.get( "treatments.title" ) } } ),
      ...chips ] } );
  },

  // The Treatments dialog for one batch; the cards catch up once it saves.
  reviewTreatments( b ) {
    Treatments.review( [ b ] ).then( ( saved ) => { if ( saved ) this.refresh( true ); } ).catch( ( e ) => App.showError( e.message ) );
  },

  folderChips( b ) {
    const adds = b.adds || [];
    if ( !adds.length ) return null;
    const chip = ( icon , name , count , title , addId , randomized ) => {
      const button = Dom.el( "button" , {
        class: "btn btn-sm btn-light border batches-folder text-truncate",
        attrs: { type: "button" , title: title },
        on: { click: () => AisImages.openBatch( b , addId ) },
        children: [ Dom.el( "i" , { class: "bi " + icon + " me-1" } ) , Dom.el( "span" , { text: name + " (" + count + ")" } ) ],
      } );
      if ( !this.admin() ) return button;
      return Dom.el( "div" , { class: "btn-group btn-group-sm batches-folder-group" , children: [ button ,
        Dom.el( "button" , {
          class: "btn btn-sm btn-light border dropdown-toggle dropdown-toggle-split",
          attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , "aria-label": I18n.get( "batches.more" ) + ": " + name },
        } ),
        Dom.el( "ul" , { class: "dropdown-menu" , children: [
          this.menuItem( "bi-grid-3x3-gap" , I18n.get( "batches.open_folder" ) , () => AisImages.openBatch( b , addId ) ),
          this.menuItem( "bi-shuffle" , I18n.get( randomized ? "batches.rerandomize_folder" : "batches.randomize_folder" ) ,
            () => this.rerandomize( b , addId , name , count ) ),
        ] } ),
      ] } );
    };
    const chips = adds.map( ( a ) => chip( a.source === "path" ? "bi-hdd" : "bi-folder2" , a.name , a.count ,
      [ a.path || a.name , I18n.get( "batches.by" ).replace( "{name}" , a.added_by_name || "?" ) , new Date( a.added_at ).toLocaleString() ]
        .concat( a.randomized ? [ I18n.get( "batches.randomized" ) ] : [] ).join( " · " ) , a.id , a.randomized ) );
    if ( b.earlier ) chips.unshift( chip( "bi-clock-history" , I18n.get( "batches.earlier" ) , b.earlier , I18n.get( "batches.earlier" ) , "earlier" , false ) );
    return Dom.el( "div" , { class: "batches-folders mt-2" , children: chips } );
  },

  // New random names for one folder's images (admins). Their AIS, done
  // marks, inclusion and assignment follow on the server; the Process
  // screen reloads the batch when it shows it again.
  async rerandomize( b , addId , name , count ) {
    const question = I18n.get( "batches.rerandomize_confirm" ).replace( "{n}" , count ).replace( "{folder}" , name );
    if ( question && !window.confirm( question ) ) return;
    let out;
    try {
      out = await Api.post( "/api/ais/batches/" + b.id + "/adds/" + addId + "/randomize" , {} );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    Dom.toast( I18n.get( "batches.rerandomized" ).replace( "{n}" , out.renamed ).replace( "{folder}" , name ).replace( "{m}" , out.measured ) );
    Ais.batchChanged( out , true );
    await this.refresh( true );
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
