// The Settings screen: which method the Process screen calculates with, and
// that method's own settings.
//
// Today there is one method, ais_auto.m (our port of the original). Another
// one is an entry in methods below plus a <fieldset data-method="key"> of its
// controls in index.html; only the chosen method's fieldset shows.
//
// Like the theme, the choice is remembered in this browser (localStorage)
// only. Move it onto the account if it should follow a person to every
// device.
const Settings = {
  storageKey: "process-settings",

  // Each method's settings and their defaults. Field -> control id in its
  // fieldset. Names come from language.yaml (settings.method_<key>).
  methods: [
    { key: "ais_auto" , defaults: { threshold: 0.01 , two_clicks: "auto" } ,
      controls: { threshold: "ais-threshold" , two_clicks: "ais-two-clicks" } },
  ],

  values: null,
  listeners: [],

  init() {
    this.values = this.load();
    const select = Dom.get( "settings-method" );
    Dom.clear( select );
    this.methods.forEach( ( method ) => {
      select.appendChild( Dom.el( "option" , { text: I18n.get( "settings.method_" + method.key ) , attrs: { value: method.key } } ) );
    } );
    select.value = this.values.method;
    select.addEventListener( "change" , () => {
      this.values = Object.assign( { method: select.value } , this.find( select.value ).defaults , this.saved( select.value ) );
      this.render();
      this.save();
    } );
    this.methods.forEach( ( method ) => {
      Object.keys( method.controls ).forEach( ( field ) => {
        Dom.get( method.controls[ field ] ).addEventListener( "change" , ( e ) => {
          const value = this.clean( method , field , e.target.value );
          this.values[ field ] = value;
          e.target.value = value;
          this.save();
        } );
      } );
    } );
    this.render();
  },

  find( key ) {
    return this.methods.find( function ( method ) { return method.key === key; } ) || this.methods[ 0 ];
  },

  // A number field out of range or empty goes back to its default.
  clean( method , field , value ) {
    const fallback = method.defaults[ field ];
    if ( typeof fallback !== "number" ) return value;
    const number = Number( value );
    return value === "" || !Number.isFinite( number ) || number < 0 || number > 1 ? fallback : number;
  },

  // Everything saved, per method, so switching away and back keeps each one's.
  all() {
    try {
      const raw = JSON.parse( window.localStorage.getItem( this.storageKey ) || "null" );
      return raw && typeof raw === "object" ? raw : {};
    } catch ( error ) {
      return {};  // Storage blocked or garbled: defaults.
    }
  },

  saved( key ) {
    const all = this.all();
    return all.by_method && typeof all.by_method[ key ] === "object" ? all.by_method[ key ] : {};
  },

  load() {
    const method = this.find( this.all().method );
    const values = Object.assign( { method: method.key } , method.defaults );
    const saved = this.saved( method.key );
    Object.keys( method.defaults ).forEach( ( field ) => {
      if ( field in saved ) values[ field ] = this.clean( method , field , saved[ field ] );
    } );
    return values;
  },

  save() {
    const method = this.find( this.values.method );
    const all = this.all();
    const byMethod = all.by_method && typeof all.by_method === "object" ? all.by_method : {};
    byMethod[ method.key ] = {};
    Object.keys( method.defaults ).forEach( ( field ) => { byMethod[ method.key ][ field ] = this.values[ field ]; } );
    try {
      window.localStorage.setItem( this.storageKey , JSON.stringify( { method: method.key , by_method: byMethod } ) );
    } catch ( error ) {
      // Not remembered for next time, but still used now.
    }
    this.listeners.forEach( ( listener ) => listener( this.values ) );
  },

  render() {
    const method = this.find( this.values.method );
    Dom.all( "fieldset[data-method]" , Dom.get( "settings" ) ).forEach( ( fieldset ) => {
      Dom.show( fieldset , fieldset.getAttribute( "data-method" ) === method.key );
    } );
    Object.keys( method.controls ).forEach( ( field ) => {
      Dom.get( method.controls[ field ] ).value = this.values[ field ];
    } );
  },

  // Called with the values after every change.
  onChange( listener ) {
    this.listeners.push( listener );
  },

  method() { return this.values.method; },
  threshold() { return this.values.threshold; },
  twoClicks() { return this.values.two_clicks; },
};
