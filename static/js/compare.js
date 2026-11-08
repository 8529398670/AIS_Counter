// Measurements grouped by treatment (admins): POST /api/ais/compare
// (app/analysis/compare.py) and what the exports make of it.
//
// - A batch report (AisExport.buildReport) gains two sheets once its images
//   have treatments: Original names, By treatment and Statistics (the
//   ANOVA blocks on image means and individual values; extraSheets).
// - Compare selected (the Batches screen) takes two batches or more, one
//   culture each, asks which stats to compute (choose; the ANOVA blocks by
//   default), and downloads a ZIP: comparison.xlsx (culture means, the
//   pooled groups, every test, every value), summary.csv, and per measure a
//   box plot of the culture means and the cumulative distributions, as SVG
//   and PNG (run).
//
// Measures never mix: AIS length, AIS to soma (the Measure tool's AIS
// modes), and one per Measure line type.
const Compare = {
  // The names the measure ids get, in sheets and the plots' titles.
  labels() {
    return { ais_length: I18n.get( "compare.ais_length" ) , ais_soma: I18n.get( "compare.ais_soma" ) ,
      "type:": I18n.get( "ais.measure_type_none" ) };
  },

  measureName( id ) {
    const fixed = this.labels();
    if ( fixed[ id ] ) return fixed[ id ];
    return id.startsWith( "type:" ) ? I18n.get( "compare.line" ).replace( "{type}" , id.slice( 5 ) ) : id;
  },

  treatment( name ) {
    return name || I18n.get( "treatments.none" );
  },

  // choice: { tests, units } from choose(); without one the server runs
  // every test (a batch report's Statistics sheet).
  fetch( list , choice ) {
    return Api.post( "/api/ais/compare" , Object.assign( { batch_ids: list.map( ( b ) => b.id ) , labels: this.labels() } , choice || {} ) );
  },

  // --- the dialog: which stats to compute (app/analysis/compare.py TESTS, UNITS) ---

  TESTS: [ "anova" , "tukey" , "welch" , "dunnett" , "paired" , "unpaired" , "ks" ],
  BLOCK_TESTS: [ "anova" , "tukey" , "welch" , "dunnett" ],
  UNITS: [ "culture means" , "image means" , "individual values" ],
  // Ticked each time the dialog opens: the whole ANOVA blocks, on every unit.
  DEFAULTS: [ "anova" , "tukey" , "welch" , "dunnett" , "culture means" , "image means" , "individual values" ],
  modal: null,
  resolve: null,     // choose()'s promise: { tests, units }, or null when closed

  init() {
    const element = Dom.get( "compare-modal" );
    this.modal = bootstrap.Modal.getOrCreateInstance( element );
    element.addEventListener( "hidden.bs.modal" , () => this.finish( null ) );
    const boxes = ( keys , prefix , into ) => Dom.get( into ).replaceChildren( ...keys.map( ( key ) => {
      const id = "compare-" + prefix + "-" + key.replace( / /g , "-" );
      const box = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , id , "data-key": key } } );
      box.addEventListener( "change" , () => this.check() );
      return Dom.el( "div" , { class: "form-check" , children: [ box ,
        Dom.el( "label" , { class: "form-check-label" , attrs: { for: id } , text: I18n.get( "compare." + prefix + "_" + key.replace( / /g , "_" ) ) } ) ] } );
    } ) );
    boxes( this.TESTS , "test" , "compare-tests" );
    boxes( this.UNITS , "unit" , "compare-units" );
    Dom.get( "compare-go" ).addEventListener( "click" , () => {
      const choice = this.picked();
      this.finish( choice );
      this.modal.hide();
    } );
  },

  picked() {
    const ticked = ( into ) => [ ...Dom.get( into ).querySelectorAll( "input:checked" ) ].map( ( b ) => b.dataset.key );
    return { tests: ticked( "compare-tests" ) , units: ticked( "compare-units" ) };
  },

  // The ANOVA tests need a unit; the units mean nothing without one of them.
  check() {
    const { tests , units } = this.picked();
    const blocks = tests.some( ( t ) => this.BLOCK_TESTS.includes( t ) );
    const stuck = blocks && !units.length;
    Dom.get( "compare-go" ).disabled = stuck;
    Dom.show( Dom.get( "compare-need-unit" ) , stuck );
    Dom.get( "compare-units" ).querySelectorAll( "input" ).forEach( ( b ) => { b.disabled = !blocks; } );
  },

  choose() {
    Dom.get( "compare-modal" ).querySelectorAll( "input[data-key]" ).forEach( ( b ) => { b.checked = this.DEFAULTS.includes( b.dataset.key ); } );
    this.check();
    this.modal.show();
    return new Promise( ( resolve ) => { this.resolve = resolve; } );
  },

  finish( choice ) {
    const resolve = this.resolve;
    this.resolve = null;
    if ( resolve ) resolve( choice );
  },

  header( keys ) {
    return keys.map( ( key ) => I18n.get( "compare.col_" + key ) );
  },

  // Original names and By treatment: one line per image, one per batch x
  // treatment x measure.
  imageSheets( out ) {
    return [
      { name: I18n.get( "compare.sheet_names" ) , cols: this.header( [ "batch" , "image" , "original" , "treatment" , "ais" , "mean_length" , "soma" , "mean_soma" ] ) ,
        rows: out.images.map( ( im ) => [ im.batch , im.image , im.original , this.treatment( im.treatment ) , im.ais , im.mean_length , im.soma , im.mean_soma ] ) },
      { name: I18n.get( "compare.sheet_groups" ) , cols: this.header( [ "batch" , "treatment" , "measure" , "n" , "mean" , "median" , "sd" , "sem" ] ) ,
        rows: out.groups.map( ( g ) => [ g.batch , this.treatment( g.treatment ) , this.measureName( g.measure ) , g.n , g.mean , g.median , g.sd , g.sem ] ) },
    ];
  },

  // A batch report's extra sheets, when its images have treatments (asking
  // for them first if none were ever saved); none otherwise.
  async extraSheets( items ) {
    if ( !Batches.admin() || !items.length ) return [];
    const list = items.map( ( item ) => item.batch );
    await Treatments.ensure( list , false );
    const out = await this.fetch( list );
    if ( !out.images.some( ( im ) => im.treatment ) ) return [];
    return this.imageSheets( out ).concat( out.stats.length ? [ this.statsSheet( out ) ] : [] );
  },

  pooledSheet( out ) {
    return { name: I18n.get( "compare.sheet_pooled" ) ,
      cols: this.header( [ "treatment" , "measure" , "n" , "mean" , "sd" , "sem" , "cultures" , "culture_mean" , "culture_sd" , "culture_sem" ] ) ,
      rows: out.pooled.map( ( p ) => [ p.treatment , this.measureName( p.measure ) , p.n , p.mean , p.sd , p.sem , p.cultures ,
        p.culture_mean , p.culture_sd , p.culture_sem ] ) };
  },

  // Every test, the main ANOVA block first (marked in Main), then the
  // other units' blocks and the other tests (app/analysis/compare.py).
  statsSheet( out ) {
    const stats = out.stats.map( ( s ) => [ this.measureName( s.measure ) , s.main ? "✓" : "" ,
      I18n.get( "compare.design_" + s.design.replace( / /g , "_" ) ) ,
      s.test , s.groups , s.n , s.statistic , s.p , s.p_holm , s.p == null ? "" : this.stars( s.p_holm ?? s.p ) , s.note ] );
    out.dropped.forEach( ( d ) => stats.push( [ this.measureName( d.measure ) , "" , I18n.get( "compare.design_paired" ) ,
      I18n.get( "compare.left_out" ) , d.batch , null , null , null , null , "" , I18n.get( "compare.left_out_note" ) ] ) );
    return { name: I18n.get( "compare.sheet_stats" ) ,
      cols: this.header( [ "measure" , "main" , "design" , "test" , "groups" , "n" , "statistic" , "p" , "p_holm" , "stars" , "note" ] ) ,
      rows: stats };
  },

  sheets( out ) {
    const cultures = out.groups.filter( ( g ) => g.treatment ).map( ( g ) =>
      [ g.batch , g.treatment , this.measureName( g.measure ) , g.n , g.mean , g.sd , g.sem ] );
    return [
      { name: I18n.get( "compare.sheet_cultures" ) , cols: this.header( [ "batch" , "treatment" , "measure" , "n" , "mean" , "sd" , "sem" ] ) , rows: cultures },
      this.pooledSheet( out ),
      this.statsSheet( out ),
      { name: I18n.get( "compare.sheet_values" ) , cols: this.header( [ "batch" , "image" , "original" , "treatment" , "measure" , "value" ] ) ,
        rows: out.values.map( ( v ) => [ v.batch , v.image , v.original , this.treatment( v.treatment ) , this.measureName( v.measure ) , v.value ] ) },
    ].concat( this.imageSheets( out ).slice( 0 , 1 ) );
  },

  stars( p ) {
    if ( p == null ) return "";
    return p < 0.001 ? "***" : p < 0.01 ? "**" : p < 0.05 ? "*" : "ns";
  },

  // An SVG drawn onto a canvas at twice its size, as PNG bytes. A data:
  // address, since the page's CSP allows those for images and not blob:.
  async png( svg ) {
    const image = new Image();
    const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent( svg );
    {
      await new Promise( ( resolve , reject ) => {
        image.onload = resolve;
        image.onerror = () => reject( new Error( "plot could not be drawn" ) );
        image.src = url;
      } );
      const canvas = document.createElement( "canvas" );
      canvas.width = image.naturalWidth * 2;
      canvas.height = image.naturalHeight * 2;
      const ctx = canvas.getContext( "2d" );
      ctx.scale( 2 , 2 );
      ctx.drawImage( image , 0 , 0 );
      const blob = await new Promise( ( resolve ) => canvas.toBlob( resolve , "image/png" ) );
      return new Uint8Array( await blob.arrayBuffer() );
    }
  },

  // Compare selected: treatments checked first (the dialog opens while any
  // image has none), then the ZIP. note( text ) shows how far it got.
  async run( list , note ) {
    if ( list.length < 2 ) {
      App.showError( I18n.get( "compare.need_two" ) );
      return;
    }
    note( I18n.get( "compare.checking" ) );
    try {
      if ( !await Treatments.ensure( list , true ) ) return;
      note( "" );
      const choice = await this.choose();
      if ( !choice ) return;
      note( I18n.get( "compare.working" ) );
      const out = await this.fetch( list , choice );
      if ( out.treatments.length < 2 ) {
        App.showError( I18n.get( "compare.need_treatments" ) );
        return;
      }
      const sheets = this.sheets( out );
      const files = [
        { name: "comparison.xlsx" , data: new Uint8Array( await Xlsx.build( sheets ).arrayBuffer() ) },
        { name: "summary.csv" , data: AisExport.sheetCsv( sheets[ 1 ] ) },
      ];
      for ( const plot of out.plots ) {
        const base = plot.kind + "_" + AisExport.safe( plot.measure.replace( ":" , "_" ) || "measure" );
        files.push( { name: base + ".svg" , data: plot.svg } );
        try {
          files.push( { name: base + ".png" , data: await this.png( plot.svg ) } );
        } catch ( error ) { /* the SVG is still there */ }
      }
      AisExport.download( Zip.build( files ) , "comparison_" + new Date().toISOString().slice( 0 , 10 ) + ".zip" );
    } catch ( error ) {
      App.showError( error.message );
    } finally {
      note( "" );
    }
  },
};
