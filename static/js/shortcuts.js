// The Keyboard shortcuts screen, and the one place that knows which key does
// what. Every key handler asks Shortcuts.is( event , "group.action" ) rather
// than comparing event.key itself, so any action can be bound to any key.
//
// Each group is a scope: its keys are checked against each other, not
// against other groups'. Measure and Auto mode keys already win over the
// Process screen's while those are on (ais.js hands them the key first), so
// the same key in two groups is how Enter can accept, save and move on.
//
// A binding is "[Mod+][Alt+][Shift+]Key". Mod is Ctrl or ⌘. Key is
// event.key, letters upper-cased and " " as Space; Shift is left off a
// single non-letter character, whose Shift is part of the character (so +
// is + on every layout). Text for each action and key comes from
// language.yaml (shortcuts.actions.<group>.<action>, shortcuts.key_names,
// and shortcuts.key_names_mac on a Mac).
//
// Only the keys someone changed are kept, on their account (POST
// /api/account/shortcuts; /api/me hands them back), so they follow a person
// to every device.
const Shortcuts = {
  // Each group's actions and their default keys, in the order shown.
  groups: [
    { key: "ais" , actions: {
      undo: [ "Mod+Z" ] , redo: [ "Mod+Y" , "Mod+Shift+Z" ] ,
      accept: [ "Enter" , "Space" ] , reject: [ "N" ] , cancel_edit: [ "Escape" ] ,
      next_image: [ "ArrowRight" , "PageDown" ] , prev_image: [ "ArrowLeft" , "PageUp" ] ,
      tool_trace: [ "T" ] , tool_edit: [ "E" ] , tool_delete: [ "D" ] , tool_measure: [ "M" ] ,
      zoom_in: [ "+" , "=" ] , zoom_out: [ "-" , "_" ] , reset_view: [ "0" ] , actual_size: [ "1" ] ,
      lock_view: [ "L" ] , focus: [ "F" ] ,
      nudge_left: [ "Alt+ArrowLeft" ] , nudge_right: [ "Alt+ArrowRight" ] ,
      nudge_up: [ "Alt+ArrowUp" ] , nudge_down: [ "Alt+ArrowDown" ] ,
      nudge_big_left: [ "Alt+Shift+ArrowLeft" ] , nudge_big_right: [ "Alt+Shift+ArrowRight" ] ,
      nudge_big_up: [ "Alt+Shift+ArrowUp" ] , nudge_big_down: [ "Alt+Shift+ArrowDown" ] } },
    { key: "measure" , actions: {
      save_next: [ "Enter" , "Space" ] , skip: [ "N" ] , next_ais: [ "]" ] , prev_ais: [ "[" ] ,
      swap_end: [ "S" ] , switch_end: [ "Tab" ] , let_go: [ "Escape" ] , delete_line: [ "Backspace" , "Delete" ] ,
      nudge_left: [ "ArrowLeft" ] , nudge_right: [ "ArrowRight" ] , nudge_up: [ "ArrowUp" ] , nudge_down: [ "ArrowDown" ] ,
      nudge_big_left: [ "Shift+ArrowLeft" ] , nudge_big_right: [ "Shift+ArrowRight" ] ,
      nudge_big_up: [ "Shift+ArrowUp" ] , nudge_big_down: [ "Shift+ArrowDown" ] } },
    { key: "auto" , actions: { next: [ "Enter" , "Space" ] , skip: [ "N" ] , stop: [ "Escape" ] } },
    { key: "images" , actions: { select_all: [ "Mod+A" ] , use_selected: [ "Enter" ] } },
    { key: "batches" , actions: { save_name: [ "Enter" ] , cancel_name: [ "Escape" ] } },
  ],

  // The same shape the server accepts (app/models/users.py SHORTCUT_KEY).
  pattern: /^(Mod\+)?(Alt\+)?(Shift\+)?([^+\s]|\+|[A-Za-z0-9]{2,20})$/,
  maxKeys: 4,
  modifierKeys: [ "Shift" , "Control" , "Alt" , "AltGraph" , "Meta" , "OS" , "Super" , "Hyper" , "Fn" , "CapsLock" , "NumLock" , "ScrollLock" ],

  // action id -> keys, for the actions whose keys are not the defaults.
  overrides: {},
  // The action waiting for a key on this screen, or null.
  capturing: null,
  // The last save sent to the account (see save).
  saving: Promise.resolve(),

  init( me ) {
    const saved = me && me.shortcuts && typeof me.shortcuts === "object" ? me.shortcuts : {};
    this.overrides = {};
    Object.keys( saved ).forEach( ( id ) => {
      // An action this build does not have (an older or newer one's) is dropped.
      if ( !this.defaults( id ) || !Array.isArray( saved[ id ] ) ) return;
      this.overrides[ id ] = saved[ id ].filter( ( key ) => typeof key === "string" && this.pattern.test( key ) ).slice( 0 , this.maxKeys );
    } );
    Dom.get( "shortcuts-reset-all" ).addEventListener( "click" , () => this.resetAll() );
    // Ahead of every other key handler, so the key being bound does nothing else.
    window.addEventListener( "keydown" , ( e ) => this.onCapture( e ) , true );
    window.addEventListener( "click" , () => this.cancel() , true );
    window.addEventListener( "hashchange" , () => this.cancel() );
    this.render();
    this.refreshText();
  },

  // --- keys ------------------------------------------------------------------

  defaults( id ) {
    const parts = String( id ).split( "." );
    const group = this.groups.find( ( g ) => g.key === parts[ 0 ] );
    return group && parts.length === 2 && group.actions[ parts[ 1 ] ] ? group.actions[ parts[ 1 ] ] : null;
  },

  bindings( id ) {
    return ( this.overrides[ id ] || this.defaults( id ) || [] ).slice();
  },

  // The binding a keydown is, or "" for a modifier on its own (or a key the
  // browser cannot name).
  eventBinding( event ) {
    let key = event.key;
    if ( !key || key === "Dead" || key === "Unidentified" || key === "Process" || this.modifierKeys.includes( key ) ) return "";
    // macOS's Alt turns letters and digits into other characters (Alt+N is ˜).
    if ( event.altKey && /^(Key[A-Z]|Digit[0-9])$/.test( event.code || "" ) ) key = event.code.slice( -1 );
    if ( key === " " || key === "Spacebar" ) key = "Space";
    const single = key.length === 1;
    const letter = single && key.toUpperCase() !== key.toLowerCase();
    if ( letter ) key = key.toUpperCase();
    const shift = event.shiftKey && !( single && !letter );
    return ( event.ctrlKey || event.metaKey ? "Mod+" : "" ) + ( event.altKey ? "Alt+" : "" ) + ( shift ? "Shift+" : "" ) + key;
  },

  is( event , id ) {
    const binding = this.eventBinding( event );
    return binding !== "" && this.bindings( id ).includes( binding );
  },

  // --- text ------------------------------------------------------------------

  // Keys are named for the computer in use: "⇧⌘Z" and "⌥←" on a Mac,
  // "Ctrl+Shift+Z" and "Alt+←" elsewhere.
  mac: /mac|iphone|ipad/i.test( ( navigator.userAgentData && navigator.userAgentData.platform ) || navigator.platform || "" ),

  // One binding as shown. A Mac's names (shortcuts.key_names_mac) win over
  // the usual ones, and its modifiers go in Apple's order with no "+".
  keyText( binding ) {
    const parts = binding.match( this.pattern );
    if ( !parts ) return binding;
    const name = ( key ) => ( this.mac && I18n.get( "shortcuts.key_names_mac." + key ) ) || I18n.get( "shortcuts.key_names." + key ) || key;
    if ( this.mac ) return [ parts[ 2 ] && "Alt" , parts[ 3 ] && "Shift" , parts[ 1 ] && "Mod" ].filter( Boolean ).map( name ).join( "" ) + name( parts[ 4 ] );
    return [ parts[ 1 ] && "Mod" , parts[ 2 ] && "Alt" , parts[ 3 ] && "Shift" ].filter( Boolean ).map( name ).concat( name( parts[ 4 ] ) ).join( "+" );
  },

  // An action's keys as shown in a sentence: "Enter or Space", "N".
  // language.yaml puts it in text as {key:group.action} (see I18n.get).
  label( id ) {
    const keys = this.bindings( id ).map( ( binding ) => this.keyText( binding ) );
    if ( !keys.length ) return I18n.get( "shortcuts.unbound" );
    if ( keys.length === 1 ) return keys[ 0 ];
    return keys.slice( 0 , -1 ).join( ", " ) + " " + I18n.get( "shortcuts.or" ) + " " + keys[ keys.length - 1 ];
  },

  actionName( id ) {
    return I18n.get( "shortcuts.actions." + id ) || id;
  },

  // Text that names a key ({key:…} in language.yaml) again, after a change.
  // Buttons whose title the Process screen sets itself are set again by it.
  refreshText() {
    I18n.apply( document , ( key ) => I18n.raw( key ).includes( "{key:" ) );
    if ( Ais.canvas ) {
      Ais.renderViewTools();
      Ais.renderFocus();
    }
  },

  // --- changes ---------------------------------------------------------------

  // Keep an action's keys, dropping the override when they are the defaults.
  store( id , keys ) {
    if ( JSON.stringify( keys ) === JSON.stringify( this.defaults( id ) ) ) delete this.overrides[ id ];
    else this.overrides[ id ] = keys;
  },

  // Take a key away from every other action of id's group: the action it
  // was on, or null.
  takeFrom( id , binding ) {
    const group = id.split( "." )[ 0 ];
    let moved = null;
    Object.keys( this.groups.find( ( g ) => g.key === group ).actions ).forEach( ( action ) => {
      const other = group + "." + action;
      const keys = this.bindings( other );
      if ( other === id || !keys.includes( binding ) ) return;
      this.store( other , keys.filter( ( key ) => key !== binding ) );
      moved = other;
    } );
    return moved;
  },

  // A key taken by another action of the same group moves here.
  add( id , binding ) {
    const moved = this.takeFrom( id , binding );
    const keys = this.bindings( id );
    if ( !keys.includes( binding ) && keys.length < this.maxKeys ) keys.push( binding );
    this.store( id , keys );
    this.save();
    if ( moved ) {
      Dom.toast( I18n.get( "shortcuts.moved" ).replace( "{key}" , this.keyText( binding ) ).replace( "{action}" , this.actionName( moved ) ) , "ok" );
    }
  },

  remove( id , binding ) {
    this.store( id , this.bindings( id ).filter( ( key ) => key !== binding ) );
    return this.save();
  },

  // Its default keys come back, from whichever actions took them since.
  reset( id ) {
    delete this.overrides[ id ];
    this.defaults( id ).forEach( ( binding ) => this.takeFrom( id , binding ) );
    return this.save();
  },

  resetAll() {
    this.overrides = {};
    return this.save();
  },

  // Used at once; the whole map goes to the account each time. One request
  // at a time, each sending the map as it is by then, so quick changes
  // cannot land out of order.
  save() {
    this.capturing = null;
    this.render();
    this.refreshText();
    this.saving = this.saving.then( () => Api.saveShortcuts( this.overrides ) ).catch( () => {
      Dom.toast( I18n.get( "shortcuts.save_failed" ) , "error" );
    } );
    return this.saving;
  },

  // --- binding a key ---------------------------------------------------------

  start( id ) {
    this.capturing = id;
    this.render();
  },

  cancel() {
    if ( this.capturing === null ) return;
    this.capturing = null;
    this.render();
  },

  // Any key at all is taken, Esc and Tab too: Cancel is a button.
  onCapture( event ) {
    if ( this.capturing === null ) return;
    const binding = this.eventBinding( event );
    if ( binding === "" ) return;   // a modifier on its own: wait for the key
    event.preventDefault();
    event.stopImmediatePropagation();
    if ( !this.pattern.test( binding ) ) return;
    this.add( this.capturing , binding );
  },

  // --- the screen ------------------------------------------------------------

  render() {
    const root = Dom.get( "shortcuts-groups" );
    Dom.clear( root );
    this.groups.forEach( ( group ) => {
      const rows = Object.keys( group.actions ).map( ( action ) => this.row( group.key + "." + action ) );
      root.appendChild( Dom.el( "fieldset" , { class: "mb-4" , children: [
        Dom.el( "legend" , { class: "h6" , text: I18n.get( "shortcuts.groups." + group.key ) } ),
        Dom.el( "p" , { class: "form-text mt-0" , text: I18n.get( "shortcuts.groups_help." + group.key ) } ),
        Dom.el( "table" , { class: "table table-sm align-middle shortcuts-table" , children: [ Dom.el( "tbody" , { children: rows } ) ] } ),
      ] } ) );
    } );
    Dom.all( "p.form-text:empty" , root ).forEach( ( p ) => p.remove() );
    Dom.show( Dom.get( "shortcuts-reset-all" ) , Object.keys( this.overrides ).length > 0 );
  },

  row( id ) {
    const keys = this.bindings( id );
    const cell = Dom.el( "td" , { class: "shortcuts-keys" } );
    keys.forEach( ( binding ) => {
      const text = this.keyText( binding );
      cell.appendChild( Dom.el( "span" , { class: "shortcut-key" , children: [
        Dom.el( "kbd" , { text: text } ),
        Dom.el( "button" , { class: "btn btn-link btn-sm p-0" , attrs: { type: "button" , title: I18n.get( "shortcuts.remove" ).replace( "{key}" , text ) , "aria-label": I18n.get( "shortcuts.remove" ).replace( "{key}" , text ) } ,
          children: [ Dom.el( "i" , { class: "bi bi-x" , attrs: { "aria-hidden": "true" } } ) ] , on: { click: () => this.remove( id , binding ) } } ),
      ] } ) );
    } );
    if ( !keys.length ) cell.appendChild( Dom.el( "span" , { class: "text-body-secondary" , text: I18n.get( "shortcuts.unbound" ) } ) );
    if ( this.capturing === id ) {
      cell.appendChild( Dom.el( "span" , { class: "shortcut-press" , text: I18n.get( "shortcuts.press" ) } ) );
      cell.appendChild( Dom.el( "button" , { class: "btn btn-outline-secondary btn-sm" , text: I18n.get( "shortcuts.cancel" ) , attrs: { type: "button" } } ) );
    } else if ( keys.length < this.maxKeys ) {
      cell.appendChild( Dom.el( "button" , { class: "btn btn-outline-secondary btn-sm" , attrs: { type: "button" } ,
        children: [ Dom.el( "i" , { class: "bi bi-plus" , attrs: { "aria-hidden": "true" } } ) , document.createTextNode( " " + I18n.get( "shortcuts.add" ) ) ] ,
        // After the window's click handler has cancelled any other capture.
        on: { click: () => this.start( id ) } } ) );
    }
    const changed = id in this.overrides;
    const reset = Dom.el( "button" , { class: "btn btn-link btn-sm" , text: I18n.get( "shortcuts.reset" ) , attrs: { type: "button" } , on: { click: () => this.reset( id ) } } );
    Dom.show( reset , changed );
    return Dom.el( "tr" , { class: changed ? "shortcut-changed" : "" , children: [
      Dom.el( "th" , { class: "fw-normal" , text: this.actionName( id ) , attrs: { scope: "row" } } ),
      cell,
      Dom.el( "td" , { class: "text-end" , children: [ reset ] } ),
    ] } );
  },
};
