// Just enough of TIFF to draw a thumbnail of a picked file without uploading
// it: the first image, uncompressed, 8- or 16-bit greyscale, in strips, either
// byte order. That is what ImageJ writes and what the example data is.
// Anything else returns null and the caller shows a placeholder.
const Tiff = {
  // width, height, bits per sample, compression, strip offsets, samples per
  // pixel, rows per strip
  wanted: [ 256 , 257 , 258 , 259 , 273 , 277 , 278 ],

  // A greyscale thumbnail canvas, min..max scaled like imagesc, long side
  // about `side` pixels (every k-th pixel, no averaging).
  async thumbnail( file , side ) {
    const buffer = await file.arrayBuffer();
    const image = this.decode( buffer );
    if ( !image ) return null;
    const step = Math.max( 1 , Math.ceil( Math.max( image.width , image.height ) / ( side || 256 ) ) );
    const w = Math.ceil( image.width / step );
    const h = Math.ceil( image.height / step );
    const sample = new Float64Array( w * h );
    let lo = Infinity;
    let hi = -Infinity;
    for ( let y = 0; y < h; y += 1 ) {
      for ( let x = 0; x < w; x += 1 ) {
        const v = image.at( x * step , y * step );
        sample[ y * w + x ] = v;
        if ( v < lo ) lo = v;
        if ( v > hi ) hi = v;
      }
    }
    const canvas = document.createElement( "canvas" );
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext( "2d" );
    const data = ctx.createImageData( w , h );
    const span = hi > lo ? hi - lo : 1;
    for ( let i = 0; i < sample.length; i += 1 ) {
      const g = Math.round( ( sample[ i ] - lo ) / span * 255 );
      data.data[ i * 4 ] = data.data[ i * 4 + 1 ] = data.data[ i * 4 + 2 ] = g;
      data.data[ i * 4 + 3 ] = 255;
    }
    ctx.putImageData( data , 0 , 0 );
    return canvas;
  },

  // { samples , rgb } of the first IFD (samples per pixel, photometric RGB),
  // for the channels a TIFF has (Channels.readTiff); null if not a TIFF.
  samples( view ) {
    if ( view.byteLength < 8 ) return null;
    const order = view.getUint16( 0 );
    if ( order !== 0x4949 && order !== 0x4d4d ) return null;
    const le = order === 0x4949;
    if ( view.getUint16( 2 , le ) !== 42 ) return null;
    const ifd = view.getUint32( 4 , le );
    const count = view.getUint16( ifd , le );
    let samples = 1;
    let photometric = null;
    for ( let i = 0; i < count; i += 1 ) {
      const at = ifd + 2 + i * 12;
      const tag = view.getUint16( at , le );
      if ( tag !== 262 && tag !== 277 ) continue;
      const type = view.getUint16( at + 2 , le );
      const value = type === 3 ? view.getUint16( at + 8 , le ) : view.getUint32( at + 8 , le );
      if ( tag === 277 ) samples = value;
      else photometric = value;
    }
    return { samples: samples || 1 , rgb: photometric === 2 };
  },

  // { width, height, at( x, y ) } for the first IFD, or null if unsupported.
  decode( buffer ) {
    try {
      return this.decodeFirst( new DataView( buffer ) );
    } catch ( error ) {
      return null;   // a truncated or odd file: no thumbnail
    }
  },

  decodeFirst( view ) {
    if ( view.byteLength < 8 ) return null;
    const order = view.getUint16( 0 );
    if ( order !== 0x4949 && order !== 0x4d4d ) return null;
    const le = order === 0x4949;
    if ( view.getUint16( 2 , le ) !== 42 ) return null;
    const ifd = view.getUint32( 4 , le );
    const count = view.getUint16( ifd , le );
    const tags = {};
    for ( let i = 0; i < count; i += 1 ) {
      const at = ifd + 2 + i * 12;
      const tag = view.getUint16( at , le );
      // Only the layout tags; ImageJ's long metadata tags are never read.
      if ( !this.wanted.includes( tag ) ) continue;
      const type = view.getUint16( at + 2 , le );
      if ( type !== 3 && type !== 4 ) continue;
      const n = view.getUint32( at + 4 , le );
      const size = type === 3 ? 2 : 4;
      const base = n * size <= 4 ? at + 8 : view.getUint32( at + 8 , le );
      const values = [];
      for ( let k = 0; k < n && k < 100000; k += 1 ) {
        values.push( size === 2 ? view.getUint16( base + k * 2 , le ) : view.getUint32( base + k * 4 , le ) );
      }
      tags[ tag ] = values;
    }
    const width = ( tags[ 256 ] || [] )[ 0 ];
    const height = ( tags[ 257 ] || [] )[ 0 ];
    const bits = ( tags[ 258 ] || [ 1 ] )[ 0 ];
    const compression = ( tags[ 259 ] || [ 1 ] )[ 0 ];
    const samples = ( tags[ 277 ] || [ 1 ] )[ 0 ];
    const offsets = tags[ 273 ];
    const rowsPerStrip = ( tags[ 278 ] || [ height ] )[ 0 ];
    if ( !width || !height || !offsets || compression !== 1 || ( bits !== 8 && bits !== 16 ) ) return null;
    const bytes = bits / 8;
    const rowBytes = width * samples * bytes;
    return {
      width: width,
      height: height,
      at( x , y ) {
        const strip = Math.floor( y / rowsPerStrip );
        const p = offsets[ strip ] + ( y - strip * rowsPerStrip ) * rowBytes + x * samples * bytes;
        if ( p + bytes > view.byteLength ) return 0;
        return bytes === 2 ? view.getUint16( p , le ) : view.getUint8( p );
      },
    };
  },
};
