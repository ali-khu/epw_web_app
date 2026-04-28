document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('uwgForm');
    const epwInput = document.getElementById('epwFile');
    const dropZone = document.getElementById('dropZone');
    const fileNameEl = document.getElementById('epwFileName');
    const btnRun = document.getElementById('btnRun');
    const resultArea = document.getElementById('resultArea');
    const resultSuccess = document.getElementById('resultSuccess');
    const resultError = document.getElementById('resultError');
    const downloadLink = document.getElementById('downloadLink');
    const errorMsg = document.getElementById('errorMsg');

    // Drag & drop
    dropZone.addEventListener('click', () => epwInput.click());
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            epwInput.files = e.dataTransfer.files;
            fileNameEl.textContent = '✅ ' + e.dataTransfer.files[0].name;
        }
    });
    epwInput.addEventListener('change', () => {
        if (epwInput.files.length) fileNameEl.textContent = '✅ ' + epwInput.files[0].name;
    });

    // Building stock sum validator
    const bldInputs = document.querySelectorAll('.bld-input');
    const bldSumEl = document.getElementById('bldSum');
    const bldNotice = document.getElementById('bldSumNotice');
    function updateBldSum() {
        let sum = 0;
        bldInputs.forEach(inp => sum += parseFloat(inp.value) || 0);
        bldSumEl.textContent = sum.toFixed(2);
        if (Math.abs(sum - 1.0) < 0.001) {
            bldNotice.className = 'bld-notice valid';
        } else {
            bldNotice.className = 'bld-notice invalid';
        }
    }
    bldInputs.forEach(inp => inp.addEventListener('input', updateBldSum));
    updateBldSum();

    // Sidebar active tracking
    const sections = document.querySelectorAll('.form-section');
    const navLinks = document.querySelectorAll('.section-nav a');
    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                navLinks.forEach(l => l.classList.remove('active'));
                const link = document.querySelector(`.section-nav a[href="#${entry.target.id}"]`);
                if (link) link.classList.add('active');
            }
        });
    }, { rootMargin: '-20% 0px -70% 0px' });
    sections.forEach(s => observer.observe(s));

    // Form submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        resultArea.style.display = 'none';
        resultSuccess.style.display = 'none';
        resultError.style.display = 'none';

        if (!epwInput.files.length) {
            alert('Please upload an EPW file.');
            return;
        }

        // Collect params
        const v = (name) => form.querySelector(`[name="${name}"]`)?.value ?? '';

        const params = {
            urban_chars: {
                bldHeight: v('uc_bldHeight'), bldDensity: v('uc_bldDensity'), verToHor: v('uc_verToHor'),
                h_mix: v('uc_h_mix'), charLength: v('uc_charLength'), albRoad: v('uc_albRoad'),
                dRoad: v('uc_dRoad'), kRoad: v('uc_kRoad'), cRoad: v('uc_cRoad'),
                sensAnth: v('uc_sensAnth'), latAnth: v('uc_latAnth')
            },
            zone: v('zone'),
            vegetation: {
                vegCover: v('veg_vegCover'), treeCoverage: v('veg_treeCoverage'),
                vegStart: v('veg_vegStart'), vegEnd: v('veg_vegEnd'), albVeg: v('veg_albVeg'),
                latGrss: v('veg_latGrss'), latTree: v('veg_latTree'), rurVegCover: v('veg_rurVegCover')
            },
            traffic: {
                weekday: v('traffic_weekday').trim().replace(/\s+/g,'') + (v('traffic_weekday').trim().endsWith(',') ? '' : ','),
                saturday: v('traffic_saturday').trim().replace(/\s+/g,'') + (v('traffic_saturday').trim().endsWith(',') ? '' : ','),
                sunday: v('traffic_sunday').trim().replace(/\s+/g,'') + (v('traffic_sunday').trim().endsWith(',') ? '' : ',')
            },
            building_stock: {},
            optional_urban: { albRoof: v('opt_albRoof'), vegRoof: v('opt_vegRoof'), glzR: v('opt_glzR'), hvac: v('opt_hvac') },
            simulation: { Month: v('sim_Month'), Day: v('sim_Day'), nDay: v('sim_nDay'), dtSim: v('sim_dtSim'), dtWeather: v('sim_dtWeather') },
            hvac_internal: { autosize: v('hvac_autosize'), sensOcc: v('hvac_sensOcc'), LatFOcc: v('hvac_LatFOcc'), RadFOcc: v('hvac_RadFOcc'), RadFEquip: v('hvac_RadFEquip'), RadFLight: v('hvac_RadFLight') },
            urban_climate: { h_ubl1: v('clim_h_ubl1'), h_ubl2: v('clim_h_ubl2'), h_ref: v('clim_h_ref'), h_temp: v('clim_h_temp'), h_wind: v('clim_h_wind'), c_circ: v('clim_c_circ'), c_exch: v('clim_c_exch'), maxDay: v('clim_maxDay'), maxNight: v('clim_maxNight'), windMin: v('clim_windMin'), h_obs: v('clim_h_obs') }
        };

        // Building stock
        const bldTypes = ["FullServiceRestaurant","Hospital","LargeHotel","LargeOffice","MediumOffice","MidRiseApartment","OutPatient","PrimarySchool","QuickServiceRestaurant","SecondarySchool","SmallHotel","SmallOffice","Stand-aloneRetail","StripMall","SuperMarket","Warehouse"];
        bldTypes.forEach(bt => {
            params.building_stock[bt] = [0,1,2].map(era => {
                const inp = document.querySelector(`.bld-input[data-type="${bt}"][data-era="${era}"]`);
                return parseFloat(inp?.value) || 0;
            });
        });

        // Validate bld sum
        let bldSum = 0;
        Object.values(params.building_stock).forEach(arr => arr.forEach(v => bldSum += v));
        if (Math.abs(bldSum - 1.0) > 0.01) {
            if (!confirm(`Building stock fractions sum to ${bldSum.toFixed(2)} instead of 1.0. Continue anyway?`)) return;
        }

        // Submit
        const fd = new FormData();
        fd.append('epw_file', epwInput.files[0]);
        fd.append('params', JSON.stringify(params));

        btnRun.disabled = true;
        btnRun.querySelector('.btn-text').style.display = 'none';
        btnRun.querySelector('.btn-loading').style.display = 'inline';

        try {
            const resp = await fetch('/api/run-uwg', { method: 'POST', body: fd });
            const data = await resp.json();
            resultArea.style.display = 'block';
            if (data.status === 'success') {
                resultSuccess.style.display = 'block';
                downloadLink.href = data.download_url;
            } else {
                resultError.style.display = 'block';
                errorMsg.textContent = data.message || 'Unknown error occurred.';
            }
        } catch (err) {
            resultArea.style.display = 'block';
            resultError.style.display = 'block';
            errorMsg.textContent = 'Network error: ' + err.message;
        } finally {
            btnRun.disabled = false;
            btnRun.querySelector('.btn-text').style.display = 'inline';
            btnRun.querySelector('.btn-loading').style.display = 'none';
        }
    });
});
