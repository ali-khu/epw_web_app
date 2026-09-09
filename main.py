import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import geopandas as gpd

# Spatial & Geocoding imports
from geopy.geocoders import Nominatim
import openpyxl
from shapely.geometry import Point

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="SUEWS Urban Microclimate Platform v1")
app.add_middleware(
    SessionMiddleware, secret_key="suews-secret-key-change-in-production"
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
USERS_FILE = Path("users.xlsx")
SHAPEFILE_PATH = Path("Seoul_hexagon_250m_SUEWS_input_shapefile/Seoul_hexagon_250m_SUEWS_input.shp")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Load Hexagon Grid Shapefile into memory on startup
hex_gdf = None
if SHAPEFILE_PATH.exists():
  try:
    hex_gdf = gpd.read_file(SHAPEFILE_PATH)
    print(f"Successfully loaded hexagon grid shapefile: {SHAPEFILE_PATH}")
  except Exception as e:
    print(f"Error loading shapefile: {e}")
else:
  print(f"Warning: Shapefile not found at {SHAPEFILE_PATH}")

# Initialize OpenStreetMap Nominatim Geolocator
geolocator = Nominatim(user_agent="seoul_suews_microclimate_platform")


def load_users():
  if not USERS_FILE.exists():
    return {"admin": "admin123"}
  wb = openpyxl.load_workbook(USERS_FILE)
  ws = wb.active
  users = {}
  for row in ws.iter_rows(min_row=2, values_only=True):
    if row[0] and row[1]:
      users[str(row[0]).strip()] = str(row[1]).strip()
  return users


def get_current_user(request: Request):
  return request.session.get("user")


def require_login(request: Request):
  user = get_current_user(request)
  if not user:
    raise HTTPException(status_code=401, detail="Not authenticated")
  return user


# ---- Auth Routes ----
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
  user = get_current_user(request)
  if user:
    return RedirectResponse(url="/dashboard", status_code=302)
  return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
  return templates.TemplateResponse(
      request=request, name="login.html", context={"error": None}
  )


@app.post("/login")
async def login(request: Request):
  form = await request.form()
  username = form.get("username", "").strip()
  password = form.get("password", "").strip()
  users = load_users()
  if username in users and users[username] == password:
    request.session["user"] = username
    return RedirectResponse(url="/dashboard", status_code=302)
  return templates.TemplateResponse(
      request=request,
      name="login.html",
      context={"error": "Invalid username or password"},
  )


@app.get("/logout")
async def logout(request: Request):
  request.session.clear()
  return RedirectResponse(url="/login", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
  user = get_current_user(request)
  if not user:
    return RedirectResponse(url="/login", status_code=302)
  return templates.TemplateResponse(
      request=request, name="dashboard.html", context={"user": user}
  )


# ---- Spatial Lookup API ----
@app.post("/api/get-location-params")
async def get_location_params(request: Request, address: str = Form(...)):
  user = get_current_user(request)
  if not user:
    raise HTTPException(status_code=401, detail="Not authenticated")

  if hex_gdf is None:
    raise HTTPException(
        status_code=500, detail="Seoul hexagon shapefile is not loaded."
    )

  search_query = (
      f"{address}, Seoul, South Korea"
      if "Seoul" not in address
      else address
  )

  try:
    location = geolocator.geocode(search_query)
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Geocoding service error: {str(e)}"
    )

  if not location:
    raise HTTPException(
        status_code=400,
        detail="Address could not be found. Please enter a valid Seoul address.",
    )

  lat, lon = location.latitude, location.longitude

  try:
    point_wgs84 = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    point_projected = point_wgs84.to_crs(hex_gdf.crs).iloc[0]
    matched_hex = hex_gdf[hex_gdf.geometry.contains(point_projected)]
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Spatial matching error: {str(e)}"
    )

  if matched_hex.empty:
    raise HTTPException(
        status_code=404,
        detail="Selected address is outside the Seoul 250m hexagon grid bounds.",
    )

  raw_params = matched_hex.iloc[0].to_dict()
  raw_params.pop("geometry", None)

  # Sanitize numpy data types for JSON serialization
  clean_params = {}
  for key, val in raw_params.items():
    if hasattr(val, "item"):
      clean_params[key] = val.item()
    else:
      clean_params[key] = val

  # 2. Create WGS84 Point and reproject to match Shapefile CRS
    point_wgs84 = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    point_projected = point_wgs84.to_crs(hex_gdf.crs).iloc[0]

    # Extract transformed metric coordinates (m)
    proj_x = round(point_projected.x, 2)
    proj_y = round(point_projected.y, 2)

    return JSONResponse({
        "status": "success",
        "formatted_address": location.address,
        "coordinates": {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "proj_x": proj_x,
            "proj_y": proj_y,
        },
        "parameters": clean_params,
    })


# ---- Simulation Runner API Placeholder ----
@app.post("/api/run-suews")
async def run_suews(
    request: Request,
    epw_file: UploadFile = File(None),
    params: str = Form(...),
):
  user = get_current_user(request)
  if not user:
    raise HTTPException(status_code=401)

  data = json.loads(params)
  job_id = str(uuid.uuid4())[:8]

  return JSONResponse({
      "status": "success",
      "job_id": job_id,
      "message": "SUEWS simulation engine execution initialized.",
  })


@app.get("/api/download/{job_id}/{filename}")
async def download_file(request: Request, job_id: str, filename: str):
  user = get_current_user(request)
  if not user:
    raise HTTPException(status_code=401)
  fpath = OUTPUT_DIR / job_id / filename
  if not fpath.exists():
    raise HTTPException(status_code=404, detail="File not found")
  return FileResponse(
      fpath, filename=filename, media_type="application/octet-stream"
  )


if __name__ == "__main__":
  import uvicorn

  uvicorn.run(app, host="0.0.0.0", port=8000)