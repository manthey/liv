(async () => {
  const imageServer = '.';
  const imageId = '5d5c07539114c049342b66fb';

  const tileinfo = await fetch(
    `${imageServer}/metadata`
  ).then(response => response.json());
  let params = geo.util.pixelCoordinateParams(
    '#map', tileinfo.sizeX, tileinfo.sizeY, tileinfo.tileWidth, tileinfo.tileHeight);
  const map = geo.map(params.map);
  params.layer.url = `${imageServer}/zxy/{z}/{x}/{y}`;
  const layer = map.createLayer('osm', params.layer);

  map.geoOn(geo.event.mousemove, function (evt) {
    $('#info').text('x: ' + evt.geo.x.toFixed(6) + ', y: ' + evt.geo.y.toFixed(6));
  });

  return null;
})();
