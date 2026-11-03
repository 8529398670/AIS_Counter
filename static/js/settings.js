// The Settings screen: which method the Process screen calculates with, and
// that method's own settings.
//
// Today there is one method, ais_auto.m (our port of the original). Another
// one is an entry in methods below plus a <fieldset data-method="key"> of its
// controls in index.html; only the chosen method's fieldset shows.
//
// General settings (minimum length, trace thickness, and how auto mode runs)
// apply whatever the method, and are kept apart from any one method's.
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

  // Settings for every method: field -> default, control id and allowed range
  // (numbers) or choices (text). A true/false default is a checkbox.
  general: {
    // auto_method: "classic" is auto mode as it always was (auto_start and
    // the auto_ filters); "fitted", the default, is the trial one fitted to hand-clicked AIS
    // (start "fitted" in app/analysis/detect.py, and the fitted_ filters);
    // "fitted2" a second trial (start "fitted2", the fitted2_ filters);
    // "learned" its own detector (start "learned", app/analysis/learned.py)
    // with a lowest score and length.
    defaults: { min_length: 0 , line_width: 1.5 ,
      auto_review: "each" , auto_method: "fitted" , auto_start: "soma" , auto_min_length: 5 , auto_min_brightness: 30 ,
      auto_min_width: 2.4 , auto_max_soma_gap: 10 ,
      fitted_min_length: 13 , fitted_min_brightness: 55 , fitted_max_branchiness: 1.02 ,
      fitted2_min_length: 13 , fitted2_min_contrast: 30 , fitted2_min_brightness: 0 , fitted2_max_branchiness: 1.02 ,
      learned_min_score: 25 , learned_min_length: 0 ,
      auto_skip_done: true },
    controls: { min_length: "settings-min-length" , line_width: "settings-line-width" ,
      auto_review: "settings-auto-review" , auto_method: "settings-auto-method" , auto_start: "settings-auto-start" ,
      auto_min_length: "settings-auto-min-length" , auto_min_brightness: "settings-auto-min-brightness" ,
      auto_min_width: "settings-auto-min-width" , auto_max_soma_gap: "settings-auto-max-soma-gap" ,
      fitted_min_length: "settings-fitted-min-length" , fitted_min_brightness: "settings-fitted-min-brightness" ,
      fitted_max_branchiness: "settings-fitted-max-branchiness" ,
      fitted2_min_length: "settings-fitted2-min-length" , fitted2_min_contrast: "settings-fitted2-min-contrast" ,
      fitted2_min_brightness: "settings-fitted2-min-brightness" , fitted2_max_branchiness: "settings-fitted2-max-branchiness" ,
      learned_min_score: "settings-learned-min-score" , learned_min_length: "settings-learned-min-length" ,
      auto_skip_done: "settings-auto-skip-done" },
    ranges: { min_length: [ 0 , 1000 ] , line_width: [ 0.5 , 6 ] , auto_min_length: [ 0 , 1000 ] ,
      auto_min_brightness: [ 0 , 100 ] , auto_min_width: [ 0 , 20 ] , auto_max_soma_gap: [ 0 , 100 ] ,
      fitted_min_length: [ 0 , 1000 ] , fitted_min_brightness: [ 0 , 100 ] , fitted_max_branchiness: [ 0 , 10 ] ,
      fitted2_min_length: [ 0 , 1000 ] , fitted2_min_contrast: [ 0 , 100 ] , fitted2_min_brightness: [ 0 , 100 ] ,
      fitted2_max_branchiness: [ 0 , 10 ] , learned_min_score: [ 0 , 100 ] , learned_min_length: [ 0 , 1000 ] },
    choices: { auto_review: [ "each" , "end" , "all" ] , auto_method: [ "classic" , "fitted" , "fitted2" , "learned" ] ,
      auto_start: [ "soma" , "both" , "brighter" , "dimmer" ] },
    // A build that briefly made the fitted filters the auto_ ones (marked by
    // auto_max_branchiness) saved its values there: they move to fitted_,
    // and the auto_ ones go back to their defaults.
    interim: { auto_min_length: "fitted_min_length" , auto_min_brightness: "fitted_min_brightness" ,
      auto_max_branchiness: "fitted_max_branchiness" , auto_start: null , auto_min_width: null , auto_max_soma_gap: null },
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
        const value = this.clean( this.general , field , control.type === "checkbox" ? e.target.checked : e.target.value );
        this.values[ field ] = value;
        if ( control.type !== "range" && control.type !== "checkbox" ) e.target.value = value;
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
  // (group.ranges), else 0..1. So does a choice not in group.choices, or a
  // checkbox that is not true or false.
  clean( group , field , value ) {
    const fallback = group.defaults[ field ];
    if ( typeof fallback === "boolean" ) return typeof value === "boolean" ? value : fallback;
    const choices = group.choices && group.choices[ field ];
    if ( choices ) return choices.includes( value ) ? value : fallback;
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
    const stored = Object.assign( {} , all.general && typeof all.general === "object" ? all.general : {} );
    if ( "auto_max_branchiness" in stored ) {
      Object.entries( this.general.interim ).forEach( ( [ from , to ] ) => {
        if ( to && from in stored ) stored[ to ] = stored[ from ];
        delete stored[ from ];
      } );
    }
    const general = this.pick( this.general , stored );
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
      const control = Dom.get( this.general.controls[ field ] );
      if ( control.type === "checkbox" ) control.checked = this.values[ field ];
      else control.value = this.values[ field ];
    } );
    this.renderGeneral();
  },

  renderGeneral() {
    Dom.text( Dom.get( "settings-line-width-value" ) , this.values.line_width + " px" );
    const method = this.values.auto_method;
    Dom.show( Dom.get( "settings-auto-classic" ) , method === "classic" );
    Dom.show( Dom.get( "settings-auto-fitted" ) , method === "fitted" );
    Dom.show( Dom.get( "settings-auto-fitted2" ) , method === "fitted2" );
    Dom.show( Dom.get( "settings-auto-learned" ) , method === "learned" );
  },

  // A general setting changed elsewhere (the Auto panel): cleaned, shown
  // here too, saved. Returns the value kept.
  setGeneral( field , value ) {
    const kept = this.clean( this.general , field , value );
    this.values[ field ] = kept;
    const control = Dom.get( this.general.controls[ field ] );
    if ( control.type === "checkbox" ) control.checked = kept;
    else control.value = kept;
    this.renderGeneral();
    this.save();
    return kept;
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
  // µm per pixel (the Measure tool's distances).
  pixconv() { return this.values.pixconv; },
  // µm; 0 is off.
  minLength() { return this.values.min_length; },
  // Screen pixels, whatever the zoom.
  lineWidth() { return this.values.line_width; },
  // Auto mode (ais_auto.js): each | end | all, classic | fitted | fitted2 | learned,
  // classic's soma | both | brighter | dimmer and filters (µm, % of the
  // image's bright level, µm, and µm from a soma on a .czi; 0 is off),
  // fitted's filters (µm, %, skeleton over trace length; 0 is off), fitted2's
  // (µm, % contrast, %, skeleton over trace length; 0 is off), learned's
  // (% score, µm; 0 is off), and whether complete images are left alone.
  autoReview() { return this.values.auto_review; },
  autoMethod() { return this.values.auto_method; },
  autoStart() { return this.values.auto_start; },
  autoMinLength() { return this.values.auto_min_length; },
  autoMinBrightness() { return this.values.auto_min_brightness; },
  autoMinWidth() { return this.values.auto_min_width; },
  autoMaxSomaGap() { return this.values.auto_max_soma_gap; },
  fittedMinLength() { return this.values.fitted_min_length; },
  fittedMinBrightness() { return this.values.fitted_min_brightness; },
  fittedMaxBranchiness() { return this.values.fitted_max_branchiness; },
  fitted2MinLength() { return this.values.fitted2_min_length; },
  fitted2MinContrast() { return this.values.fitted2_min_contrast; },
  fitted2MinBrightness() { return this.values.fitted2_min_brightness; },
  fitted2MaxBranchiness() { return this.values.fitted2_max_branchiness; },
  learnedMinScore() { return this.values.learned_min_score; },
  learnedMinLength() { return this.values.learned_min_length; },
  autoSkipDone() { return this.values.auto_skip_done; },
};
