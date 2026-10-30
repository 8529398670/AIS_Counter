// The Settings screen: which method the Process screen calculates with, and
// that method's own settings.
//
// Today there is one method, ais_auto.m (our port of the original). Another
// one is an entry in methods below plus a <fieldset data-method="key"> of its
// controls in index.html; only the chosen method's fieldset shows.
//
// General settings (minimum length, trace thickness) apply whatever the
// method, and are kept apart from any one method's.
//
// Like the theme, the choice is remembered in this browser (localStorage)
// only. Move it onto the account if it should follow a person to every
// device.
const Settings = {
  storageKey: "process-settings",

  // Each method's settings and their defaults. Field -> control id in its
  // fieldset. Names come from language.yaml (settings.method_<key>).
  methods: [
    // ais_auto: threshold and smooth are the original's arguments; the
    // constants it hard-codes (app/analysis/ais_auto.py Settings) follow,
    // with the same ranges the server checks.
    { key: "ais_auto" ,
      defaults: { threshold: 0.01 , two_clicks: "auto" , smooth: "gaussian" ,
        pixconv: 0.161 , f: 0.33 , kernel: 20 , sigma: 2 , strel: 3 , min_pixels: 70 ,
        max_path: 300 , max_passes: 10 , spline_p: 0.3 , window_um: 1.5 } ,
      controls: { threshold: "ais-threshold" , two_clicks: "ais-two-clicks" , smooth: "ais-smooth" ,
        pixconv: "ais-pixconv" , f: "ais-f" , kernel: "ais-kernel" , sigma: "ais-sigma" , strel: "ais-strel" ,
        min_pixels: "ais-min-pixels" , max_path: "ais-max-path" , max_passes: "ais-max-passes" ,
        spline_p: "ais-spline-p" , window_um: "ais-window-um" } ,
      ranges: { pixconv: [ 0.0001 , 1000 ] , kernel: [ 1 , 201 ] , sigma: [ 0.01 , 100 ] , strel: [ 1 , 25 ] ,
        min_pixels: [ 0 , 10000000 ] , max_path: [ 1 , 100000 ] , max_passes: [ 1 , 1000 ] , window_um: [ 0.001 , 1000 ] } ,
      integers: [ "kernel" , "strel" , "min_pixels" , "max_path" , "max_passes" ] ,
      // Sent to the server as settings; the rest are the call's or this screen's.
      sent: [ "smooth" , "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ] ,
      constants: [ "pixconv" , "f" , "kernel" , "sigma" , "strel" , "min_pixels" , "max_path" , "max_passes" , "spline_p" , "window_um" ] },
  ],

  // Settings for every method: field -> default, control id and allowed range.
  general: {
    defaults: { min_length: 0 , line_width: 1.5 },
    controls: { min_length: "settings-min-length" , line_width: "settings-line-width" },
    ranges: { min_length: [ 0 , 1000 ] , line_width: [ 0.5 , 6 ] },
  },

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
      const general = this.pick( this.general , this.values );
      this.values = Object.assign( { method: select.value } , general , this.find( select.value ).defaults , this.saved( select.value ) );
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
    // The slider redraws as it moves; the number box once it is left.
    Object.keys( this.general.controls ).forEach( ( field ) => {
      const control = Dom.get( this.general.controls[ field ] );
      control.addEventListener( control.type === "range" ? "input" : "change" , ( e ) => {
        const value = this.clean( this.general , field , e.target.value );
        this.values[ field ] = value;
        if ( control.type !== "range" ) e.target.value = value;
        this.renderGeneral();
        this.save();
      } );
    } );
    // Back to the original's constants, for the method shown.
    Dom.get( "ais-constants-reset" ).addEventListener( "click" , () => {
      const method = this.find( this.values.method );
      ( method.constants || [] ).forEach( ( field ) => { this.values[ field ] = method.defaults[ field ]; } );
      this.render();
      this.save();
    } );
    this.render();
  },

  find( key ) {
    return this.methods.find( function ( method ) { return method.key === key; } ) || this.methods[ 0 ];
  },

  // A number field out of range, empty or (for a whole-number field) not
  // whole goes back to its default. The range is the group's own
  // (group.ranges), else 0..1.
  clean( group , field , value ) {
    const fallback = group.defaults[ field ];
    if ( typeof fallback !== "number" ) return value;
    const range = ( group.ranges && group.ranges[ field ] ) || [ 0 , 1 ];
    const number = Number( value );
    const whole = !( group.integers || [] ).includes( field ) || Number.isInteger( number );
    return value === "" || !Number.isFinite( number ) || !whole || number < range[ 0 ] || number > range[ 1 ] ? fallback : number;
  },

  // A group's fields from values, cleaned, defaults for anything missing.
  pick( group , values ) {
    const out = {};
    Object.keys( group.defaults ).forEach( ( field ) => {
      out[ field ] = values && field in values ? this.clean( group , field , values[ field ] ) : group.defaults[ field ];
    } );
    return out;
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
    const all = this.all();
    const general = this.pick( this.general , all.general && typeof all.general === "object" ? all.general : {} );
    const values = Object.assign( { method: method.key } , general , method.defaults );
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
      const general = this.pick( this.general , this.values );
      window.localStorage.setItem( this.storageKey , JSON.stringify( { method: method.key , by_method: byMethod , general: general } ) );
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
    Object.keys( this.general.controls ).forEach( ( field ) => {
      Dom.get( this.general.controls[ field ] ).value = this.values[ field ];
    } );
    this.renderGeneral();
  },

  renderGeneral() {
    Dom.text( Dom.get( "settings-line-width-value" ) , this.values.line_width + " px" );
  },

  // Called with the values after every change.
  onChange( listener ) {
    this.listeners.push( listener );
  },

  // The method and its fields, as one string: whether a change was to them.
  methodState() {
    const method = this.find( this.values.method );
    return JSON.stringify( [ method.key ].concat( Object.keys( method.defaults ).map( ( field ) => this.values[ field ] ) ) );
  },

  method() { return this.values.method; },
  threshold() { return this.values.threshold; },
  // The method's settings the server takes (the trace and MATLAB bodies).
  methodSettings() {
    const method = this.find( this.values.method );
    const out = {};
    ( method.sent || [] ).forEach( ( field ) => { out[ field ] = this.values[ field ]; } );
    return out;
  },
  twoClicks() { return this.values.two_clicks; },
  // µm; 0 is off.
  minLength() { return this.values.min_length; },
  // Screen pixels, whatever the zoom.
  lineWidth() { return this.values.line_width; },
};
