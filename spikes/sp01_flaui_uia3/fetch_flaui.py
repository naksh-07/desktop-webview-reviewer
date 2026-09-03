import urllib.request
import json
import zipfile
import os
import shutil

lib_dir = os.path.abspath(r"spikes\sp01_flaui_uia3\lib")
os.makedirs(lib_dir, exist_ok=True)

packages = ["FlaUI.Core", "FlaUI.UIA3", "Interop.UIAutomationClient"]

for pkg in packages:
    try:
        print(f"Checking NuGet for {pkg}...")
        url = f"https://api.nuget.org/v3-flatcontainer/{pkg.lower()}/index.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            versions = data["versions"]
            # Find latest non-preview or stable version
            stable_versions = [v for v in versions if "-" not in v]
            target_version = stable_versions[-1] if stable_versions else versions[-1]
            print(f"Latest version for {pkg}: {target_version}")
            
            nupkg_url = f"https://api.nuget.org/v3-flatcontainer/{pkg.lower()}/{target_version}/{pkg.lower()}.{target_version}.nupkg"
            nupkg_path = os.path.join(lib_dir, f"{pkg}.nupkg")
            print(f"Downloading {nupkg_url} -> {nupkg_path}...")
            urllib.request.urlretrieve(nupkg_url, nupkg_path)
            
            with zipfile.ZipFile(nupkg_path, 'r') as zf:
                for member in zf.namelist():
                    if member.endswith(".dll") and ("lib/net4" in member or "lib/net48" in member or "lib/net47" in member or "lib/net45" in member or "lib/netstandard2.0" in member):
                        filename = os.path.basename(member)
                        target_file = os.path.join(lib_dir, filename)
                        print(f"Extracting {member} -> {target_file}")
                        with zf.open(member) as src, open(target_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            if os.path.exists(nupkg_path):
                os.remove(nupkg_path)
    except Exception as e:
        print(f"Error fetching {pkg}: {e}")

print("Extracted libraries in", lib_dir, ":", os.listdir(lib_dir))
