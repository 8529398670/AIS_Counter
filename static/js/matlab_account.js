// The MATLAB part of the Account screen: where MATLAB is on this person's
// computer (written into their replay zips, app/analysis/matlab_bundle.py), and
// connecting the helper (helper/, app/routes/ais_matlab.py).
//
// For a browser session only: the server refuses these from an API key.
const MatlabAccount = {
  ready: false,

  init( me ) {
    if ( me.auth !== "session" ) return;
    this.ready = true;
    Dom.show( Dom.get( "matlab-panel" ) , true );
    Dom.get( "matlab-path" ).value = me.matlab_path || "";
    Dom.get( "matlab-path-form" ).addEventListener( "submit" , this.onSave.bind( this ) );
    Dom.get( "matlab-helper-connect" ).addEventListener( "click" , this.onConnect.bind( this ) );
    [ "unix" , "windows" ].forEach( ( os ) => {
      Dom.get( "matlab-helper-" + os + "-copy" ).addEventListener( "click" , () => Dom.copy( Dom.get( "matlab-helper-" + os ) ) );
    } );
  },

  // Ais.loadLocal calls this whenever it learns whether the helper is running.
  render() {
    if ( !this.ready ) return;
    Dom.show( Dom.get( "matlab-helper" ) , Boolean( Ais.local.helper_enabled ) );
    const status = Dom.get( "matlab-helper-status" );
    Dom.text( status , I18n.get( Ais.local.helper ? "matlab.helper_on" : "matlab.helper_off" ) );
    status.className = "badge " + ( Ais.local.helper ? "text-bg-success" : "text-bg-secondary" );
  },

  async onSave( event ) {
    event.preventDefault();
    try {
      const saved = await Api.saveMatlabPath( Dom.get( "matlab-path" ).value );
      Dom.get( "matlab-path" ).value = saved.path;
      Dom.toast( I18n.get( "ui.saved" ) , "ok" );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // Curl rather than a browser download: a browser marks the file as from the
  // internet, and macOS then refuses to run an unsigned program. uname picks
  // the build, which a browser cannot tell (Intel or Apple Silicon).
  async onConnect() {
    try {
      const { credential: key } = await Api.mintHelperKey();
      const origin = window.location.origin;
      const fetchFrom = "-fL -H \"Authorization: Bearer " + key + "\" " + origin + "/api/ais/matlab/helper/download/";
      Dom.text( Dom.get( "matlab-helper-unix" ) ,
        "curl " + fetchFrom + "$(uname -s)-$(uname -m) -o ais-matlab-helper && chmod +x ais-matlab-helper" +
        " && ./ais-matlab-helper connect " + origin + " " + key + " && ./ais-matlab-helper" );
      Dom.text( Dom.get( "matlab-helper-windows" ) ,
        "curl.exe " + fetchFrom + "windows-amd64 -o ais-matlab-helper.exe" +
        " && ais-matlab-helper.exe connect " + origin + " " + key + " && ais-matlab-helper.exe" );
      Dom.show( Dom.get( "matlab-helper-box" ) , true );
    } catch ( error ) {
      App.showError( error.message );
    }
  },
};
