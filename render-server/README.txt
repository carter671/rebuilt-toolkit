REBUILT RENDER SERVER
Photo-real renders of Rebuilt models on this PC's graphics card (RTX: OptiX).

ONE-TIME SETUP
  1. Install Blender 4.2 LTS or newer (free): https://www.blender.org/download/
  2. Unzip this folder anywhere, e.g. C:\Rebuilt\render-server
  3. Double-click TEST.bat. In about a minute you should see "GPU: OPTIX NVIDIA GeForce RTX 3080"
     and an image in outputs\waterloo-d2\00-smoke-test. If it says "none found", update the NVIDIA driver.

RENDERING
  RENDER.bat   renders every job in the jobs folder once, then stops.
  WATCH.bat    stays running and renders any new job file dropped into jobs\ (use this as the "server").
  Close the window to stop. The PC only needs to be on while it renders.

JOBS ALREADY QUEUED (7244 Waterloo Rd, Option D-2), with rough RTX 3080 times:
  01-kitchen-still   sharp kitchen still, 2560x1440                      ~1-2 min
  02-kitchen-360     sharp 360° kitchen, 8192x4096                       ~10-20 min
  03-exteriors       sharp street + rear stills, 2560x1440               ~2-4 min
  04-full-tour       all 13 tour stops as sharp 360°s, 6144x3072         ~1-2 hrs
  Delete a job file to skip it. Results land in outputs\waterloo-d2\<job name>\.

FOLDERS
  projects\   models exported by Claude (model.glb + genome.json + site.json per property / design)
  presets\    camera views, 360° stops, resolution and quality
  jobs\       the queue; finished jobs move to jobs\done, failed ones to jobs\failed (details in outputs\_errors)
  outputs\    the images
  status.json what the server is doing right now

GETTING THE IMAGES ONTO THE TOUR
  Open the Rebuilt chat in the Claude desktop app on this PC: Claude can then queue jobs, run them and
  publish the finished images to the tour and render pages for you. Or send the files from outputs\ in the chat.
