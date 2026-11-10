// The About screen: what the Process screen draws, the MATLAB it can call,
// and the full report on the original (docs/ais_auto_report.md).
//
// The colour legend, numbers, keys and MATLAB list are plain markup in
// index.html with their text in language.yaml. The report is not copied
// anywhere: /api/about/report serves the file in docs/, fetched the first
// time this screen opens and rendered with the vendored marked.
//
// The Instructions screen is markup only; its contents links scroll the same way.
//
// In-page links (#about-measures, the report's own #1-summary contents) scroll
// instead of changing the URL hash, which Nav reads as the screen to show.
const About = {
  loaded: false,

  init( me ) {
    this.facts( me );
    Dom.get( "about" ).addEventListener( "click" , ( e ) => this.onLink( e ) );
    Dom.get( "instructions" ).addEventListener( "click" , ( e ) => this.onLink( e ) );
    window.addEventListener( "hashchange" , () => this.maybeLoad() );
    this.maybeLoad();
  },

  // The card at the top: app.description, the running version, app.repo and
  // where to read the API reference, all from /api/me. Shown only while
  // app.show_about is on; the rest of the screen is always there.
  facts( me ) {
    if ( me.show_about !== true ) return;
    const description = Dom.get( "about-description" );
    Dom.text( description , me.description || "" );
    Dom.show( description , Boolean( me.description ) );
    Dom.text( Dom.get( "about-version" ) , me.version || "" );
    this.link( "about-source" , me.repo , me.repo );
    this.link( "about-api" , me.openapi_url );
    Dom.show( Dom.get( "about-facts-card" ) , true );
  },

  // A link and its row, shown only when there is somewhere to go. text, when
  // given, replaces the link's label.
  link( id , href , text ) {
    const anchor = Dom.get( id );
    const shown = typeof href === "string" && href !== "";
    if ( shown ) anchor.setAttribute( "href" , href );
    if ( shown && text ) Dom.text( anchor , text );
    Dom.show( anchor.parentElement , shown );
    Dom.show( anchor.parentElement.previousElementSibling , shown );
  },

  maybeLoad() {
    if ( this.loaded || window.location.hash.replace( /^#/ , "" ).split( "/" )[ 0 ] !== "about" ) return;
    this.loaded = true;
    this.load();
  },

  async load() {
    const box = Dom.get( "about-report-body" );
    try {
      const report = await Api.request( "/api/about/report" );
      box.innerHTML = this.render( report.markdown );
      Dom.all( "table" , box ).forEach( ( table ) => {
        table.classList.add( "table" , "table-sm" , "table-bordered" );
        const wrap = Dom.el( "div" , { class: "table-responsive" } );
        table.replaceWith( wrap );
        wrap.appendChild( table );
      } );
    } catch ( error ) {
      this.loaded = false;
      Dom.clear( box );
      box.appendChild( Dom.el( "p" , { class: "text-danger" , text: I18n.get( "about.report_error" ) } ) );
    }
  },

  // GitHub's heading ids, so the report's contents links work, prefixed so
  // they cannot collide with the app's own ids. The report is this repo's own
  // file, but raw HTML in it is still shown as text rather than run.
  render( markdown ) {
    const self = this;
    const md = new marked.Marked( {
      gfm: true,
      renderer: {
        heading( token ) {
          const id = self.reportId( self.slug( token.text ) );
          return "<h" + ( token.depth + 1 ) + ' id="' + id + '">' + this.parser.parseInline( token.tokens ) + "</h" + ( token.depth + 1 ) + ">\n";
        },
        html( token ) {
          return self.escape( token.text );
        },
        link( token ) {
          const href = token.href.charAt( 0 ) === "#" ? "#" + self.reportId( token.href.slice( 1 ) ) : token.href;
          return '<a href="' + self.escape( href ) + '">' + this.parser.parseInline( token.tokens ) + "</a>";
        },
      },
    } );
    return md.parse( markdown );
  },

  slug( text ) {
    return text.toLowerCase().trim().replace( /[^\p{L}\p{N}\s_-]/gu , "" ).replace( /\s/g , "-" );
  },

  reportId( slug ) {
    return "report-" + slug;
  },

  escape( text ) {
    return String( text ).replace( /&/g , "&amp;" ).replace( /</g , "&lt;" ).replace( />/g , "&gt;" ).replace( /"/g , "&quot;" );
  },

  onLink( e ) {
    const link = e.target.closest( 'a[href^="#"]' );
    if ( !link ) return;
    const target = document.getElementById( decodeURIComponent( link.getAttribute( "href" ).slice( 1 ) ) );
    // A link to another screen (#instructions) changes screen as usual.
    if ( !target || target.classList.contains( "view" ) ) return;
    e.preventDefault();
    target.scrollIntoView( { behavior: "smooth" , block: "start" } );
  },
};
