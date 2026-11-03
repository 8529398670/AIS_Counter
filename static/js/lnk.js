// A Windows shortcut (.lnk, the Shell Link format) to a file by relative
// path, for the Original-names folder of a ZIP export unpacked on Windows,
// where symbolic links do not survive. Only the header and the relative path:
// Windows finds the target from where the shortcut itself sits.
const Lnk = {
  // relative: "..\\..\\originals\\123-456-789.czi" -> Uint8Array
  build( relative ) {
    const target = relative.replace( /\//g , "\\" );
    const header = new DataView( new ArrayBuffer( 76 ) );
    header.setUint32( 0 , 76 , true );
    // LinkCLSID 00021401-0000-0000-C000-000000000046
    [ 0x01 , 0x14 , 0x02 , 0x00 , 0x00 , 0x00 , 0x00 , 0x00 , 0xc0 , 0x00 , 0x00 , 0x00 , 0x00 , 0x00 , 0x00 , 0x46 ]
      .forEach( ( byte , i ) => header.setUint8( 4 + i , byte ) );
    header.setUint32( 20 , 0x08 | 0x80 , true );   // HasRelativePath | IsUnicode
    header.setUint32( 24 , 0x20 , true );          // FILE_ATTRIBUTE_ARCHIVE
    header.setUint32( 60 , 1 , true );             // SW_SHOWNORMAL
    const path = new DataView( new ArrayBuffer( 2 + 2 * target.length ) );
    path.setUint16( 0 , target.length , true );
    for ( let i = 0; i < target.length; i += 1 ) path.setUint16( 2 + 2 * i , target.charCodeAt( i ) , true );
    const out = new Uint8Array( 76 + path.byteLength + 4 );   // + the empty ExtraData terminator
    out.set( new Uint8Array( header.buffer ) , 0 );
    out.set( new Uint8Array( path.buffer ) , 76 );
    return out;
  },
};
