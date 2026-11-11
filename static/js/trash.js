// The Batches screen's trash (app/models/ais.py, /api/ais/trash): deleting a
// batch or folder, or resetting a batch, puts what went there for a while
// (TRASH_DAYS on the server) instead of losing it.
//
// Two ways back:
//   - right after, the toast's Undo (or Ctrl+Z): Trash.undoable records it
//     with Undo, restoring by trash id; Redo deletes it again.
//   - later, the Trash dialog: every entry, newest first, with Restore for
//     whoever may (the one who deleted a batch, or an admin) and Delete for
//     good for admins.
const Trash = {
  modal: null,
  entries: [],

  init() {
    this.modal = bootstrap.Modal.getOrCreateInstance( Dom.get( "batches-trash-modal" ) );
    Dom.get( "batches-trash" ).addEventListener( "click" , () => this.show() );
  },

  // After a delete the server answered with trash_id: an Undo for it.
  // again() does the delete once more and answers the new trash_id.
  // after() redraws whatever the change touched.
  undoable( label , trashId , again , after ) {
    let current = trashId;
    if ( !current ) return;
    Undo.record( {
      label: label,
      toast: true,
      undo: async () => {
        await this.restore( current );
        await after();
      },
      redo: async () => {
        current = await again();
        await after();
      },
    } );
  },

  restore( id ) {
    return Api.post( "/api/ais/trash/" + id + "/restore" , {} );
  },

  async show() {
    Dom.text( Dom.get( "batches-trash-status" ) , I18n.get( "trash.loading" ) );
    Dom.get( "batches-trash-list" ).replaceChildren();
    this.modal.show();
    await this.load();
  },

  async load() {
    let out;
    try {
      out = await Api.request( "/api/ais/trash" );
    } catch ( error ) {
      Dom.text( Dom.get( "batches-trash-status" ) , error.message );
      return;
    }
    this.entries = out.entries;
    Dom.text( Dom.get( "batches-trash-help" ) , I18n.get( "trash.help" ).replace( "{days}" , out.days ) );
    this.render();
  },

  icon( entry ) {
    return entry.kind === "folder" ? "bi-folder2" : entry.kind === "reset" ? "bi-arrow-counterclockwise" : "bi-collection";
  },

  // "Batch · 3 images, 12 AIS, 2 lines" and the like.
  what( entry ) {
    const parts = [];
    if ( entry.kind === "folder" ) {
      parts.push( I18n.get( "trash.kind_folder" ) );
      parts.push( I18n.get( "trash.count_folder" ).replace( "{batches}" , entry.batches ).replace( "{folders}" , entry.folders ) );
    } else {
      parts.push( I18n.get( entry.kind === "reset" ? ( entry.scope === "auto" ? "trash.kind_reset_auto" : "trash.kind_reset" ) : "trash.kind_batch" ) );
      const counts = I18n.get( entry.kind === "batch" ? "trash.count_batch" : "trash.count_reset" )
        .replace( "{images}" , entry.images ).replace( "{ais}" , entry.results ).replace( "{lines}" , entry.measurements );
      parts.push( counts );
    }
    return parts.join( " · " );
  },

  render() {
    const list = Dom.get( "batches-trash-list" );
    Dom.text( Dom.get( "batches-trash-status" ) , this.entries.length ? "" : I18n.get( "trash.empty" ) );
    const admin = Batches.admin();
    list.replaceChildren( ...this.entries.map( ( entry ) => {
      const buttons = [];
      if ( entry.can_restore ) {
        buttons.push( Dom.el( "button" , { class: "btn btn-outline-primary btn-sm" , attrs: { type: "button" } ,
          children: [ Dom.el( "i" , { class: "bi bi-arrow-counterclockwise me-1" , attrs: { "aria-hidden": "true" } } ) ,
            Dom.el( "span" , { text: I18n.get( "trash.restore" ) } ) ] ,
          on: { click: () => this.restoreEntry( entry ) } } ) );
      }
      if ( admin ) {
        buttons.push( Dom.el( "button" , { class: "btn btn-outline-danger btn-sm" , attrs: { type: "button" , title: I18n.get( "trash.purge" ) , "aria-label": I18n.get( "trash.purge" ) + ": " + entry.name } ,
          children: [ Dom.el( "i" , { class: "bi bi-x-lg" , attrs: { "aria-hidden": "true" } } ) ] ,
          on: { click: () => this.purge( entry ) } } ) );
      }
      const by = entry.deleted_by_name ? I18n.get( "trash.by" ).replace( "{name}" , entry.deleted_by_name ) : "";
      return Dom.el( "li" , { class: "list-group-item d-flex align-items-center gap-2" , children: [
        Dom.el( "i" , { class: "bi " + this.icon( entry ) + " text-body-secondary" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "div" , { class: "me-auto min-w-0" , children: [
          Dom.el( "div" , { class: "text-truncate fw-semibold" , text: entry.name } ),
          Dom.el( "div" , { class: "small text-body-secondary" , text: this.what( entry ) } ),
          Dom.el( "div" , { class: "small text-body-secondary" , children: [
            Dom.el( "span" , { text: I18n.get( "trash.deleted" ) + " " } ) , Dom.when( entry.deleted_at ) ,
            Dom.el( "span" , { text: by ? " " + by : "" } ) ] } ),
        ] } ),
        ...buttons,
      ] } );
    } ) );
  },

  async restoreEntry( entry ) {
    try {
      await this.restore( entry.id );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    Dom.toast( I18n.get( "trash.restored" ).replace( "{name}" , entry.name ) );
    await this.changed( entry );
    await this.load();
  },

  async purge( entry ) {
    const question = I18n.get( "trash.purge_confirm" ).replace( "{name}" , entry.name );
    if ( !( await Dom.confirm( question ) ) ) return;
    try {
      await Api.post( "/api/ais/trash/" + entry.id + "/purge" , {} );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    await this.load();
  },

  // What a restore touched: the list always, the open batch if a reset of it
  // came back (its rows reload when Process shows it).
  async changed( entry ) {
    if ( entry && entry.kind === "reset" && Ais.batch && Ais.batch.id === entry.batch_id ) {
      try {
        Ais.batchChanged( await Api.request( "/api/ais/batches/" + entry.batch_id ) , true );
      } catch ( error ) {
        // Gone again in the meantime: the list below says so.
      }
    }
    await Batches.refresh( true );
  },
};
