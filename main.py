import os, json, shutil, uuid, tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import openpyxl

app = FastAPI(title="UWG Web Interface v1")
app.add_middleware(SessionMiddleware, secret_key="uwg-secret-key-change-in-production")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
USERS_FILE = Path("users.xlsx")


def load_users():
    wb = openpyxl.load_workbook(USERS_FILE)
    ws = wb.active
    users = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]:
            users[str(row[0]).strip()] = str(row[1]).strip()
    return users


def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        return None
    return user


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
    # FIXED: Added explicitly named arguments (request=, name=, context=)
    return templates.TemplateResponse(
        request=request, 
        name="login.html", 
        context={"request": request, "error": None}
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
    
    # FIXED: Added explicitly named arguments (request=, name=, context=)
    return templates.TemplateResponse(
        request=request, 
        name="login.html", 
        context={"request": request, "error": "Invalid username or password"}
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
        
    # FIXED: Added explicitly named arguments (request=, name=, context=)
    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={"request": request, "user": user}
    )


# ---- UWG API ----
@app.post("/api/run-uwg")
async def run_uwg(request: Request, epw_file: UploadFile = File(...), params: str = Form(...)):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)

    data = json.loads(params)
    job_id = str(uuid.uuid4())[:8]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save EPW
    epw_path = job_dir / epw_file.filename
    with open(epw_path, "wb") as buf:
        shutil.copyfileobj(epw_file.file, buf)

    # Generate .uwg file
    uwg_content = generate_uwg_text(data)
    uwg_path = job_dir / "params.uwg"
    with open(uwg_path, "w") as uf:
        uf.write(uwg_content)

        # Run UWG
    try:
        from uwg import UWG
        
        # 1. Set the clean output name
        output_filename = f"UWG_refined_{epw_file.filename}"
        
        # 2. Extract the specific variables we need from the frontend's 'data' dictionary
        uc = data.get("urban_chars", {})
        vg = data.get("vegetation", {})
        sim = data.get("simulation", {})
        
        print(f"Running Urban Weather Generator for {epw_file.filename}...")
        
        # 3. Create the model using from_param_args, feeding in the frontend data!
        model = UWG.from_param_args(
            epw_path=str(epw_path),
            bldheight=float(uc.get('bldHeight', 10)),      # From frontend!
            blddensity=float(uc.get('bldDensity', 0.5)),   # From frontend!
            vertohor=float(uc.get('verToHor', 0.8)),       # From frontend!
            grasscover=float(vg.get('vegCover', 0.2)),     # From frontend!
            treecover=float(vg.get('treeCoverage', 0.1)),  # From frontend!
            zone=str(data.get('zone', '1A')),              # From frontend!
            new_epw_name=output_filename,                  # Clean output name
            month=int(sim.get('Month', 1)),                # From frontend!
            day=int(sim.get('Day', 1)),                    # From frontend!
            nday=int(sim.get('nDay', 31))                  # From frontend!
        )

        # 4. Run the simulation
        model.generate()
        model.simulate()
        model.write_epw()
        
        print(f"✅ Finished! New urban EPW file created: {output_filename}")

        # 5. Move the generated file to the secure output directory for download
        generated_epw_path = epw_path.parent / output_filename
        final_path = out_dir / output_filename
        
        if generated_epw_path.exists():
            shutil.copy2(generated_epw_path, final_path)
            return JSONResponse({
                "status": "success", 
                "download_url": f"/api/download/{job_id}/{output_filename}"
            })
        else:
            return JSONResponse({
                "status": "error", 
                "message": "UWG completed but output EPW file not found."
            }, status_code=500)

    except Exception as e:
        print(f"❌ Error running UWG: {str(e)}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
        
    finally:
        # Cleanup temporary upload directory
        shutil.rmtree(job_dir, ignore_errors=True)


@app.get("/api/download/{job_id}/{filename}")
async def download_file(request: Request, job_id: str, filename: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)
    fpath = OUTPUT_DIR / job_id / filename
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(fpath, filename=filename, media_type="application/octet-stream")


def generate_uwg_text(d):
    lines = []
    lines.append("# =================================================")
    lines.append("# UWG Parameters - Generated by UWG Web Interface")
    lines.append(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("# =================================================\n")

    lines.append("# =================================================")
    lines.append("# REQUIRED PARAMETERS")
    lines.append("# =================================================\n")

    lines.append("# Urban characteristics")
    uc = d.get("urban_chars", {})
    lines.append(f"bldHeight,{uc.get('bldHeight', 10)},")
    lines.append(f"bldDensity,{uc.get('bldDensity', 0.5)},")
    lines.append(f"verToHor,{uc.get('verToHor', 0.8)},")
    lines.append(f"h_mix,{uc.get('h_mix', 1)},")
    lines.append(f"charLength,{uc.get('charLength', 1000)},")
    lines.append(f"albRoad,{uc.get('albRoad', 0.1)},")
    lines.append(f"dRoad,{uc.get('dRoad', 0.5)},")
    lines.append(f"kRoad,{uc.get('kRoad', 1)},")
    lines.append(f"cRoad,{uc.get('cRoad', 1600000)},")
    lines.append(f"sensAnth,{uc.get('sensAnth', 20)},")
    lines.append(f"latAnth,{uc.get('latAnth', 2)},\n")

    lines.append(f"zone,{d.get('zone', 1)},\n")

    lines.append("# Vegetation parameters")
    vg = d.get("vegetation", {})
    lines.append(f"vegCover,{vg.get('vegCover', 0.2)},")
    lines.append(f"treeCoverage,{vg.get('treeCoverage', 0.1)},")
    lines.append(f"vegStart,{vg.get('vegStart', 4)},")
    lines.append(f"vegEnd,{vg.get('vegEnd', 10)},")
    lines.append(f"albVeg,{vg.get('albVeg', 0.25)},")
    lines.append(f"latGrss,{vg.get('latGrss', 0.4)},")
    lines.append(f"latTree,{vg.get('latTree', 0.6)},")
    lines.append(f"rurVegCover,{vg.get('rurVegCover', 0.9)},\n")

    lines.append("# Traffic schedule [1 to 24 hour]")
    lines.append("SchTraffic,")
    tr = d.get("traffic", {})
    lines.append(tr.get("weekday", "0.2,0.2,0.2,0.2,0.2,0.4,0.7,0.9,0.9,0.6,0.6,0.6,0.6,0.6,0.7,0.8,0.9,0.9,0.8,0.8,0.7,0.3,0.2,0.2,") + " # Weekday")
    lines.append(tr.get("saturday", "0.2,0.2,0.2,0.2,0.2,0.3,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.6,0.7,0.7,0.7,0.7,0.5,0.4,0.3,0.2,0.2,") + " # Saturday")
    lines.append(tr.get("sunday", "0.2,0.2,0.2,0.2,0.2,0.3,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.3,0.3,0.2,0.2,") + " # Sunday\n")

    lines.append("# Building stock fractions (pre-80s, 80s-present, new)")
    lines.append("bld,")
    bld_types = [
        "FullServiceRestaurant", "Hospital", "LargeHotel", "LargeOffice",
        "MediumOffice", "MidRiseApartment", "OutPatient", "PrimarySchool",
        "QuickServiceRestaurant", "SecondarySchool", "SmallHotel", "SmallOffice",
        "Stand-aloneRetail", "StripMall", "SuperMarket", "Warehouse"
    ]
    bld = d.get("building_stock", {})
    for bt in bld_types:
        vals = bld.get(bt, [0, 0, 0])
        lines.append(f"{vals[0]},{vals[1]},{vals[2]},    # {bt}")

    lines.append("\n# =================================================")
    lines.append("# OPTIONAL URBAN PARAMETERS")
    lines.append("# =================================================")
    opt = d.get("optional_urban", {})
    lines.append(f"albRoof,{opt.get('albRoof', '')},")
    lines.append(f"vegRoof,{opt.get('vegRoof', '')},")
    lines.append(f"glzR,{opt.get('glzR', '')},")
    lines.append(f"hvac,{opt.get('hvac', '')},\n")

    lines.append("# =================================================")
    lines.append("# OPTIONAL SIMULATION CONTROL")
    lines.append("# =================================================\n")

    sim = d.get("simulation", {})
    lines.append(f"Month,{sim.get('Month', 1)},")
    lines.append(f"Day,{sim.get('Day', 1)},")
    lines.append(f"nDay,{sim.get('nDay', 31)},")
    lines.append(f"dtSim,{sim.get('dtSim', 300)},")
    lines.append(f"dtWeather,{sim.get('dtWeather', 3600)},\n")

    hvac_int = d.get("hvac_internal", {})
    lines.append(f"autosize,{hvac_int.get('autosize', 0)},")
    lines.append(f"sensOcc,{hvac_int.get('sensOcc', 100)},")
    lines.append(f"LatFOcc,{hvac_int.get('LatFOcc', 0.3)},")
    lines.append(f"RadFOcc,{hvac_int.get('RadFOcc', 0.2)},")
    lines.append(f"RadFEquip,{hvac_int.get('RadFEquip', 0.5)},")
    lines.append(f"RadFLight,{hvac_int.get('RadFLight', 0.7)},\n")

    uc2 = d.get("urban_climate", {})
    lines.append(f"h_ubl1,{uc2.get('h_ubl1', 1000)},")
    lines.append(f"h_ubl2,{uc2.get('h_ubl2', 80)},")
    lines.append(f"h_ref,{uc2.get('h_ref', 150)},")
    lines.append(f"h_temp,{uc2.get('h_temp', 2)},")
    lines.append(f"h_wind,{uc2.get('h_wind', 10)},")
    lines.append(f"c_circ,{uc2.get('c_circ', 1.2)},")
    lines.append(f"c_exch,{uc2.get('c_exch', 1)},")
    lines.append(f"maxDay,{uc2.get('maxDay', 150)},")
    lines.append(f"maxNight,{uc2.get('maxNight', 20)},")
    lines.append(f"windMin,{uc2.get('windMin', 1)},")
    lines.append(f"h_obs,{uc2.get('h_obs', 0.1)},")

    return "\n".join(lines)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
