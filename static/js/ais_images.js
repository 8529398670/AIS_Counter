// The Images dialog and Open path. Images: which of a batch's images the
// team works on (stepped through, assigned, counted and exported), folder by
// folder as they were added, as preview cards or a details list, with
// duplicates. It opens on the Process screen's batch (open) or any batch
// from its card on the Batches screen (openBatch), and saves the choice to
// the server only when it is confirmed. Open path: a folder on this machine,
// read by the server, for a new batch or one the Batches screen adds to.
const AisImages = {
  ctx: null,             // what the dialog shows: see open / openBatch
  staged: [],            // the selection being edited, one boolean per image
  anchor: -1,            // last plain/Ctrl click, for Shift ranges
  hideDuplicates: true,
  thumbSide: 256,
  folder: null,          // the add shown (its id, or "earlier"), null for all
  mode: "grid",          // "grid" (cards) or "list" (details)
  sort: { col: "index" , dir: 1 },
  modeKey: "ais-images-view",

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
    try {
      if ( window.localStorage.getItem( this.modeKey ) === "list" ) this.mode = "list";
    } catch ( error ) { /* storage blocked: cards */ }

    Dom.get( "ais-images-open" ).addEventListener( "click" , () => this.open() );
    Dom.get( "ais-images-channels" ).addEventListener( "click" , () => this.editChannels() );
    Dom.get( "ais-images-all" ).addEventListener( "click" , () => this.setVisible( true ) );
    Dom.get( "ais-images-none" ).addEventListener( "click" , () => this.setVisible( false ) );
    Dom.get( "ais-images-use" ).addEventListener( "click" , () => this.confirm() );
    Dom.get( "ais-images-filter" ).addEventListener( "input" , () => this.applyFilter() );
    Dom.get( "ais-images-hide-dups" ).addEventListener( "change" , ( e ) => this.setHideDuplicates( e.target.checked ) );
    Dom.all( "[data-images-mode]" ).forEach( ( button ) => button.addEventListener( "click" ,
      () => this.setMode( button.getAttribute( "data-images-mode" ) ) ) );
    this.grid.addEventListener( "keydown" , ( e ) => {
      if ( Shortcuts.is( e , "images.select_all" ) ) { e.preventDefault(); this.setVisible( true ); }
    } );
    this.modalEl.addEventListener( "keydown" , ( e ) => {
      if ( Shortcuts.is( e , "images.use_selected" ) && e.target.tagName !== "BUTTON" ) { e.preventDefault(); this.confirm(); }
    } );

    this.initPath();
  },

  // --- Images ----------------------------------------------------------------

  entries() {
    return this.ctx ? this.ctx.entries : [];
  },

  // The Process screen's batch, its live rows and done marks.
  open() {
    if ( !Ais.images.length ) return;
    this.ctx = {
      batch: Ais.batch,
      entries: Ais.images,
      process: true,
      count: ( entry ) => Ais.acceptedCount( entry ),
      complete: ( entry ) => Ais.isComplete( entry ),
      assignee: ( entry ) => {
        const id = Ais.assigneeOf( entry );
        return id == null ? null : { id: id , name: Ais.assigneeName( id ) };
      },
    };
    this.show( null );
  },

  // Any batch (a Batches row or record), fetched now; addId opens it on that
  // add (a folder), "earlier" on images from before adds were kept.
  async openBatch( b , addId ) {
    let batch;
    let status;
    try {
      [ batch , status ] = await Promise.all( [ Api.request( "/api/ais/batches/" + b.id ) ,
        Api.request( "/api/ais/batches/" + b.id + "/status" ) ] );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    if ( !batch.images.length ) return;
    const byKey = new Map( status.images.map( ( image ) => [ image.key , image ] ) );
    const of = ( entry ) => byKey.get( entry.key ) || {};
    this.ctx = {
      batch: batch,
      entries: batch.images.map( ( image ) => ( { key: image.key , cell: image.cell , dir: image.dir , dup_of: image.dup_of ,
        add_id: image.add_id , original_key: image.original_key , channels: image.channels , files: image.files } ) ),
      process: false,
      count: ( entry ) => of( entry ).ais || 0,
      complete: ( entry ) => Boolean( of( entry ).ais || of( entry ).done ),
      assignee: ( entry ) => of( entry ).assignee != null ? { id: of( entry ).assignee , name: of( entry ).assignee_name || "" } : null,
    };
    this.show( addId == null ? null : addId );
  },

  show( folder ) {
    const entries = this.entries();
    const excluded = new Set( this.ctx.batch.excluded || [] );
    this.staged = entries.map( ( entry ) => !excluded.has( entry.key ) );
    this.anchor = -1;
    this.folder = folder;
    Dom.get( "ais-images-filter" ).value = "";
    const batch = this.ctx.batch;
    Dom.text( Dom.get( "ais-images-batch" ) , batch.path || batch.name );
    const dups = entries.filter( ( entry ) => entry.dup_of != null ).length;
    Dom.show( Dom.get( "ais-images-dups" ) , dups > 0 );
    Dom.text( Dom.get( "ais-images-dups-count" ) , I18n.get( "ais.n_duplicates" ).replace( "{n}" , dups ) );
    // Hidden by default when the batch has duplicates nobody has included.
    this.hideDuplicates = dups > 0 && entries.every( ( entry , i ) => entry.dup_of == null || !this.staged[ i ] );
    Dom.get( "ais-images-hide-dups" ).checked = this.hideDuplicates;
    Dom.get( "ais-images-use" ).disabled = false;
    this.renderFolders();
    this.render();
    if ( !this.modalEl.classList.contains( "show" ) ) {
      this.modal.show();
      this.modalEl.addEventListener( "shown.bs.modal" , () => this.grid.focus() , { once: true } );
    }
  },

  // The adds as chips: All, then each folder (or set of files) in the order
  // it came in.
  renderFolders() {
    const holder = Dom.get( "ais-images-folders" );
    Dom.clear( holder );
    const entries = this.entries();
    const adds = this.ctx.batch.adds || [];
    const earlier = entries.filter( ( entry ) => entry.add_id == null ).length;
    Dom.show( holder , adds.length > 0 );
    if ( !adds.length ) {
      this.folder = null;
      return;
    }
    const chip = ( value , icon , label , n , title ) => holder.appendChild( Dom.el( "button" , {
      class: "btn btn-sm text-truncate ais-folder " + ( this.folder === value ? "btn-primary" : "btn-outline-secondary" ),
      attrs: { type: "button" , title: title || label , "aria-pressed": String( this.folder === value ) },
      on: { click: () => { this.folder = value; this.renderFolders(); this.applyFilter(); } },
      children: [ Dom.el( "i" , { class: "bi " + icon + " me-1" } ) , Dom.el( "span" , { text: label } ) ,
        Dom.el( "span" , { class: "ms-1 opacity-75" , text: "(" + n + ")" } ) ],
    } ) );
    chip( null , "bi-collection" , I18n.get( "ais.folders_all" ) , entries.length );
    if ( earlier ) chip( "earlier" , "bi-clock-history" , I18n.get( "batches.earlier" ) , earlier );
    adds.forEach( ( a ) => chip( a.id , a.source === "path" ? "bi-hdd" : "bi-folder2" , a.name ,
      entries.filter( ( entry ) => entry.add_id === a.id ).length ,
      [ a.path || a.name , a.added_by_name , new Date( a.added_at ).toLocaleString() ].filter( Boolean ).join( " · " ) ) );
  },

  // Channel roles for the add shown (or the whole batch), saved at once;
  // the dialog then shows the batch as it is now.
  async editChannels() {
    const batch = this.ctx && this.ctx.batch;
    if ( !batch || !batch.id ) return;
    const addId = typeof this.folder === "number" ? this.folder : null;
    try {
      const saved = await Channels.edit( batch.id , addId );
      if ( saved && !this.ctx.process ) this.openBatch( batch , this.folder );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  addOf( entry ) {
    return ( this.ctx.batch.adds || [] ).find( ( a ) => a.id === entry.add_id ) || null;
  },

  setMode( mode ) {
    this.mode = mode === "list" ? "list" : "grid";
    try {
      window.localStorage.setItem( this.modeKey , this.mode );
    } catch ( error ) { /* storage blocked: this visit only */ }
    this.render();
  },

  // Save what changed (both ways) for the team. showIndex: the image a
  // double-click opens.
  async confirm( showIndex ) {
    const ctx = this.ctx;
    if ( !ctx ) return;
    const excluded = new Set( ctx.batch.excluded || [] );
    const on = [];
    const off = [];
    ctx.entries.forEach( ( entry , i ) => {
      if ( this.staged[ i ] && excluded.has( entry.key ) ) on.push( entry.key );
      if ( !this.staged[ i ] && !excluded.has( entry.key ) ) off.push( entry.key );
    } );
    const use = Dom.get( "ais-images-use" );
    use.disabled = true;
    let batch = null;
    try {
      if ( on.length ) batch = await Api.post( "/api/ais/batches/" + ctx.batch.id + "/include" , { keys: on , included: true } );
      if ( off.length ) batch = await Api.post( "/api/ais/batches/" + ctx.batch.id + "/include" , { keys: off , included: false } );
    } catch ( error ) {
      use.disabled = false;
      App.showError( error.message );
      return;
    }
    this.modal.hide();
    const now = batch ? batch.excluded : ( ctx.batch.excluded || [] );
    ctx.batch.excluded = now;
    if ( ctx.process ) {
      Ais.excludedChanged( now , showIndex != null ? showIndex : null );
    } else {
      if ( batch ) Ais.batchChanged( batch , false );
      if ( showIndex != null ) window.location.hash = Ais.urlFor( ctx.batch , ctx.entries[ showIndex ] );
    }
    if ( batch && Batches.showing() ) Batches.refresh( true );
  },

  render() {
    this.observer.disconnect();
    Dom.clear( this.grid );
    this.grid.classList.toggle( "ais-images-list" , this.mode === "list" );
    Dom.all( "[data-images-mode]" ).forEach( ( button ) => {
      const on = button.getAttribute( "data-images-mode" ) === this.mode;
      button.classList.toggle( "active" , on );
      button.setAttribute( "aria-pressed" , String( on ) );
    } );
    if ( this.mode === "list" ) this.renderList();
    else this.renderGrid();
    this.applyFilter();
  },

  // Click and double-click are the same on a card and a row.
  itemHandlers( i ) {
    return {
      click: ( e ) => this.onClick( i , e ),
      // Double-click opens the image: undo what its first click did to
      // the selection, include it, and confirm.
      dblclick: () => {
        if ( this.beforeClick ) this.staged = this.beforeClick;
        this.staged[ i ] = true;
        this.confirm( i );
      },
    };
  },

  badges( entry ) {
    const ctx = this.ctx;
    const pair = Ais.kind( entry ) === "pair";
    const czi = Ais.kind( entry ) === "czi";
    const stack = entry.files.stack;
    const count = ctx.count( entry );
    const badges = [
      Dom.el( "span" , { class: "badge " + ( pair || czi || stack ? "text-bg-secondary" : "text-bg-warning" ) ,
        text: stack ? I18n.get( "ais.z_badge" ).replace( "{n}" , stack.slices.length ) : I18n.get( czi ? "ais.czi" : pair ? "ais.pair" : "ais.single" ) } ),
    ];
    if ( entry.dup_of != null ) {
      badges.push( Dom.el( "span" , { class: "badge text-bg-danger" , text: I18n.get( "ais.duplicate_of" ).replace( "{n}" , entry.dup_of + 1 ) } ) );
    }
    if ( count ) badges.push( Dom.el( "span" , { class: "badge text-bg-success" , text: count + " AIS" } ) );
    if ( ctx.complete( entry ) ) badges.push( Dom.el( "i" , { class: "bi bi-check-circle-fill text-success" , attrs: { title: I18n.get( "ais.complete" ) } } ) );
    return badges;
  },

  assigneeBadge( entry ) {
    const owner = this.ctx.assignee( entry );
    if ( !owner ) return null;
    const me = Ais.me && owner.id === Ais.me.id;
    return Dom.el( "span" , { class: "ais-card-assignee " + ( me ? "text-primary fw-semibold" : "text-body-secondary" ) , children: [
      Dom.el( "i" , { class: "bi bi-person me-1" } ) , Dom.el( "span" , { text: owner.name } ) ] } );
  },

  renderGrid() {
    this.entries().forEach( ( entry , i ) => {
      const main = entry.files[ Ais.traced( entry ) ];
      const name = Ais.splitName( main.name );
      const pair = Ais.kind( entry ) === "pair";
      const box = Dom.el( "input" , { class: "form-check-input ais-card-check" , attrs: { type: "checkbox" , tabindex: "-1" , "aria-label": main.name } } );
      const badges = this.badges( entry );
      const owner = this.assigneeBadge( entry );
      if ( owner ) badges.push( owner );
      if ( this.ctx.process && Ais.canMatlab() ) badges.push( this.matlabMenu( entry , main.name ) );
      const card = Dom.el( "div" , {
        class: "ais-image-card ais-item" + ( this.ctx.process && i === Ais.index ? " ais-current" : "" ),
        attrs: { role: "option" , "data-index": String( i ) , title: main.name + ( entry.original_key ? " · " + entry.original_key : "" ) },
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
            entry.original_key ? Dom.el( "div" , { class: "small text-body-tertiary text-truncate ais-card-original" ,
              text: I18n.get( "ais.original_name" ) + ": " + entry.original_key } ) : Dom.el( "span" ),
            Dom.el( "div" , { class: "d-flex flex-wrap align-items-center gap-1 mt-1" , children: badges } ),
          ] } ),
        ],
        on: this.itemHandlers( i ),
      } );
      this.grid.appendChild( card );
      this.observer.observe( card );
    } );
  },

  // --- the details list ------------------------------------------------------

  // The list's columns: [ key , label key , value for sorting ]; Original
  // name only when the server sent originals (admins).
  columns() {
    const main = ( entry ) => entry.files[ Ais.traced( entry ) ];
    const size = ( entry ) => Object.values( entry.files ).reduce( ( sum , f ) => sum + ( f.size || 0 ) , 0 );
    const add = ( entry ) => this.addOf( entry );
    const cols = [
      [ "index" , "ais.col_number" , ( entry , i ) => i ],
      [ "name" , "ais.col_name" , ( entry ) => main( entry ).name.toLowerCase() ],
      [ "folder" , "ais.col_folder" , ( entry ) => ( add( entry ) ? add( entry ).name : "" ).toLowerCase() ],
      [ "dir" , "ais.col_subfolder" , ( entry ) => ( entry.dir || "" ).toLowerCase() ],
      [ "kind" , "ais.col_kind" , ( entry ) => Ais.kind( entry ) ],
      [ "size" , "ais.col_size" , size ],
      [ "modified" , "ais.col_modified" , ( entry ) => main( entry ).modified || "" ],
      [ "created" , "ais.col_created" , ( entry ) => main( entry ).created || "" ],
      [ "added" , "ais.col_added" , ( entry ) => ( add( entry ) ? add( entry ).added_at : "" ) ],
      [ "state" , "ais.col_state" , ( entry ) => ( this.ctx.complete( entry ) ? 1e6 : 0 ) + this.ctx.count( entry ) ],
      [ "assignee" , "ais.col_assignee" , ( entry ) => ( this.ctx.assignee( entry ) || { name: "" } ).name.toLowerCase() ],
    ];
    if ( this.entries().some( ( entry ) => entry.original_key ) ) {
      cols.push( [ "original" , "ais.original_name" , ( entry ) => ( entry.original_key || "" ).toLowerCase() ] );
    }
    return cols;
  },

  date( iso ) {
    return iso ? new Date( iso ).toLocaleString( [] , { dateStyle: "short" , timeStyle: "short" } ) : "";
  },

  size( bytes ) {
    if ( !bytes ) return "";
    const units = [ "B" , "KB" , "MB" , "GB" ];
    let n = bytes;
    let u = 0;
    while ( n >= 1024 && u < units.length - 1 ) { n /= 1024; u += 1; }
    return ( u ? n.toFixed( n < 10 ? 1 : 0 ) : n ) + " " + units[ u ];
  },

  renderList() {
    const cols = this.columns();
    const sortBy = cols.find( ( c ) => c[ 0 ] === this.sort.col ) || cols[ 0 ];
    const entries = this.entries();
    const order = entries.map( ( _ , i ) => i ).sort( ( a , b ) => {
      const x = sortBy[ 2 ]( entries[ a ] , a );
      const y = sortBy[ 2 ]( entries[ b ] , b );
      return ( x < y ? -1 : x > y ? 1 : a - b ) * this.sort.dir;
    } );
    const head = Dom.el( "tr" , { children: [ Dom.el( "th" , { class: "ais-list-check" } ) ].concat( cols.map( ( [ key , label ] ) => {
      const on = key === sortBy[ 0 ];
      return Dom.el( "th" , { class: "text-nowrap" , attrs: { "aria-sort": on ? ( this.sort.dir > 0 ? "ascending" : "descending" ) : "none" } , children: [
        Dom.el( "button" , { class: "btn btn-link btn-sm p-0 text-reset text-decoration-none fw-semibold" , attrs: { type: "button" } ,
          on: { click: () => {
            this.sort = { col: key , dir: on ? -this.sort.dir : 1 };
            this.render();
          } },
          children: [ Dom.el( "span" , { text: I18n.get( label ) } ) ].concat( on
            ? [ Dom.el( "i" , { class: "bi ms-1 " + ( this.sort.dir > 0 ? "bi-caret-up-fill" : "bi-caret-down-fill" ) } ) ] : [] ) } ),
      ] } );
    } ) ) } );
    const rows = order.map( ( i ) => {
      const entry = entries[ i ];
      const main = entry.files[ Ais.traced( entry ) ];
      const add = this.addOf( entry );
      const total = Object.values( entry.files ).reduce( ( sum , f ) => sum + ( f.size || 0 ) , 0 );
      const owner = this.ctx.assignee( entry );
      const cells = {
        index: String( i + 1 ),
        name: [ Dom.el( "div" , { class: "fw-semibold text-truncate" , text: main.name } ) ].concat( Ais.kind( entry ) === "pair"
          ? [ Dom.el( "div" , { class: "small text-body-secondary text-truncate" , text: "+ " + entry.files.raw.name } ) ] : [] ),
        folder: add ? add.name : ( ( this.ctx.batch.adds || [] ).length ? I18n.get( "batches.earlier" ) : "" ),
        dir: entry.dir || "",
        kind: this.badges( entry ).slice( 0 , 2 ),
        size: this.size( total ),
        modified: this.date( main.modified ),
        created: this.date( main.created ),
        added: add ? [ this.date( add.added_at ) , add.added_by_name ].filter( Boolean ).join( " · " ) : "",
        state: this.badges( entry ).slice( 2 ),
        assignee: owner ? owner.name : "",
        original: entry.original_key || "",
      };
      const box = Dom.el( "input" , { class: "form-check-input ais-card-check" , attrs: { type: "checkbox" , tabindex: "-1" , "aria-label": main.name } } );
      return Dom.el( "tr" , {
        class: "ais-item ais-image-row" + ( this.ctx.process && i === Ais.index ? " ais-row-current" : "" ),
        attrs: { role: "option" , "data-index": String( i ) , title: main.name },
        on: this.itemHandlers( i ),
        children: [ Dom.el( "td" , { class: "ais-list-check" , children: [ box ] } ) ].concat( cols.map( ( [ key ] ) => {
          const value = cells[ key ];
          const td = Dom.el( "td" , { class: "ais-list-" + key } );
          if ( Array.isArray( value ) ) value.forEach( ( node ) => td.appendChild( node ) );
          else Dom.text( td , value );
          return td;
        } ) ),
      } );
    } );
    this.grid.appendChild( Dom.el( "table" , { class: "table table-sm table-hover align-middle small mb-0 ais-images-table" , children: [
      Dom.el( "thead" , { class: "sticky-top" , children: [ head ] } ),
      Dom.el( "tbody" , { children: rows } ),
    ] } ) );
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
    const entry = this.entries()[ i ];
    if ( !entry || !holder ) return;
    const f = entry.files[ Ais.traced( entry ) ];
    // Picked on the Batches screen and still waiting to upload: read here too.
    const picked = Ais.parts( entry ).some( ( part ) => part.file || Batches.fileFor( part.sha ) );
    // A view of another channel (channel roles) is drawn by the server too.
    const viewed = Ais.sha( entry ) !== f.sha;
    const serverOnly = Ais.kind( entry ) === "czi" || Ais.kind( entry ) === "stack" || viewed;
    // A .czi or Z-stack only the server can draw: picked here and not up yet
    // (a new batch's still queued), so upload it now rather than say nobody has.
    if ( !entry.thumb && picked && !f.stored && serverOnly ) {
      holder.replaceChildren( Dom.el( "span" , { class: "small text-body-tertiary px-2 text-center" ,
        text: I18n.get( "ais.uploading" ).replace( "{name}" , f.name ) } ) );
      try {
        await Ais.upload( entry );
      } catch ( error ) { /* falls through to "not uploaded" */ }
    }
    if ( !entry.thumb ) {
      if ( picked && !serverOnly ) {
        try {
          entry.thumb = await Tiff.thumbnail( f.file || Batches.fileFor( f.sha ) , this.thumbSide );
        } catch ( error ) {
          entry.thumb = null;
        }
      } else if ( f.stored ) {
        entry.thumb = Dom.el( "img" , { attrs: { alt: "" , src: "/api/ais/files/" + Ais.sha( entry ) + "/thumb.png?v=2" } } );   // v=2: see Ais.show
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
    return Dom.all( ".ais-item" , this.grid ).filter( ( card ) => !card.hidden ).map( ( card ) => Number( card.dataset.index ) );
  },

  applyFilter() {
    const q = Dom.get( "ais-images-filter" ).value.trim().toLowerCase();
    const folder = this.folder;
    Dom.all( ".ais-item" , this.grid ).forEach( ( card ) => {
      const entry = this.entries()[ Number( card.dataset.index ) ];
      const names = ( entry.dir + " " + ( entry.original_key || "" ) + " " + Object.values( entry.files ).map( ( f ) => f.name ).join( " " ) ).toLowerCase();
      const elsewhere = folder != null && ( folder === "earlier" ? entry.add_id != null : entry.add_id !== folder );
      card.hidden = elsewhere || ( Boolean( q ) && !names.includes( q ) ) || ( this.hideDuplicates && entry.dup_of != null );
    } );
    this.refresh();
  },

  // Hiding duplicates also leaves them out; showing them again does not add
  // them back by itself.
  setHideDuplicates( on ) {
    this.hideDuplicates = on;
    if ( on ) this.entries().forEach( ( entry , i ) => { if ( entry.dup_of != null ) this.staged[ i ] = false; } );
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

  setVisible( on ) {
    this.visible().forEach( ( k ) => { this.staged[ k ] = on; } );
    this.refresh();
  },

  // Update checkboxes and counts without rebuilding the cards.
  refresh() {
    Dom.all( ".ais-item" , this.grid ).forEach( ( card ) => {
      const on = this.staged[ Number( card.dataset.index ) ];
      card.classList.toggle( "ais-selected" , on );
      card.setAttribute( "aria-selected" , String( on ) );
      card.querySelector( ".ais-card-check" ).checked = on;
    } );
    const n = this.staged.filter( Boolean ).length;
    Dom.text( Dom.get( "ais-images-selected" ) , I18n.get( "ais.n_selected" ).replace( "{n}" , n ).replace( "{total}" , this.staged.length ) );
    const done = this.entries().filter( ( entry , i ) => this.staged[ i ] && this.ctx.complete( entry ) ).length;
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
