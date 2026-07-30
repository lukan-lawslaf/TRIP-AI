from app.tools.maps import decode_polyline


def test_google_polyline_decodes_to_maplibre_coordinates():
    coordinates = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")

    assert coordinates == [
        [-120.2, 38.5],
        [-120.95, 40.7],
        [-126.453, 43.252],
    ]
