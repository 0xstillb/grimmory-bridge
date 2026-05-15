use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::Duration,
};
use tauri::{Emitter, Manager, State};
use tauri_plugin_dialog::DialogExt;
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RpcErrorPayload {
    code: i64,
    message: String,
    #[serde(default)]
    data: Option<Value>,
}

type PendingTx = mpsc::Sender<Result<Value, RpcErrorPayload>>;

struct RpcInner {
    child: Mutex<Child>,
    stdin: Mutex<ChildStdin>,
    pending: Mutex<HashMap<u64, PendingTx>>,
    next_id: AtomicU64,
}

#[derive(Clone)]
struct RpcState {
    inner: Arc<RpcInner>,
}

struct RpcRuntime {
    app: tauri::AppHandle,
    state: Mutex<Option<RpcState>>,
}

impl RpcState {
    fn call(&self, method: String, params: Value) -> Result<Value, String> {
        let id = self.inner.next_id.fetch_add(1, Ordering::Relaxed);
        let (tx, rx) = mpsc::channel::<Result<Value, RpcErrorPayload>>();
        {
            let mut pending = self
                .inner
                .pending
                .lock()
                .map_err(|_| "pending lock poisoned".to_string())?;
            pending.insert(id, tx);
        }

        let request = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params
        });
        let mut line = serde_json::to_string(&request).map_err(|e| e.to_string())?;
        line.push('\n');

        {
            let mut stdin = self
                .inner
                .stdin
                .lock()
                .map_err(|_| "stdin lock poisoned".to_string())?;
            stdin
                .write_all(line.as_bytes())
                .and_then(|_| stdin.flush())
                .map_err(|e| e.to_string())?;
        }

        match rx.recv_timeout(Duration::from_secs(30)) {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(err)) => Err(format!("{} ({})", err.message, err.code)),
            Err(_) => {
                let mut pending = self
                    .inner
                    .pending
                    .lock()
                    .map_err(|_| "pending lock poisoned".to_string())?;
                pending.remove(&id);
                Err("RPC timeout waiting for sidecar response".to_string())
            }
        }
    }
}

impl RpcRuntime {
    fn call(&self, method: String, params: Value) -> Result<Value, String> {
        let state = {
            let mut slot = self
                .state
                .lock()
                .map_err(|_| "rpc runtime lock poisoned".to_string())?;
            if let Some(state) = slot.as_ref() {
                state.clone()
            } else {
                let spawned = spawn_sidecar(self.app.clone())?;
                *slot = Some(spawned.clone());
                spawned
            }
        };
        state.call(method, params)
    }
}

fn sidecar_candidates() -> Vec<PathBuf> {
    let base = Path::new(env!("CARGO_MANIFEST_DIR")).join("binaries");
    let mut candidates = Vec::new();

    if let Ok(entries) = fs::read_dir(&base) {
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }

            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                let matches_sidecar = name.starts_with("grimmory-bridge-py-")
                    || name == "grimmory-bridge-py"
                    || name == "grimmory-bridge-py.exe";
                if matches_sidecar {
                    candidates.push(path);
                }
            }
        }
    }

    candidates.sort();
    candidates
}

fn fail_all_pending(inner: &Arc<RpcInner>, message: &str) {
    let mut pending = match inner.pending.lock() {
        Ok(p) => p,
        Err(_) => return,
    };

    for (_, tx) in pending.drain() {
        let _ = tx.send(Err(RpcErrorPayload {
            code: -32001,
            message: message.to_string(),
            data: None,
        }));
    }
}

fn route_sidecar_line(app: &tauri::AppHandle, inner: &Arc<RpcInner>, line: &str) {
    let parsed: Value = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(err) => {
            eprintln!("[sidecar] invalid JSON line: {err}");
            return;
        }
    };

    if let Some(id) = parsed.get("id").and_then(Value::as_u64) {
        let tx = {
            let mut pending = match inner.pending.lock() {
                Ok(p) => p,
                Err(_) => return,
            };
            pending.remove(&id)
        };

        if let Some(tx) = tx {
            if let Some(err_val) = parsed.get("error") {
                let err = serde_json::from_value::<RpcErrorPayload>(err_val.clone()).unwrap_or(
                    RpcErrorPayload {
                        code: -32603,
                        message: "Internal error".to_string(),
                        data: Some(err_val.clone()),
                    },
                );
                let _ = tx.send(Err(err));
            } else {
                let result = parsed.get("result").cloned().unwrap_or(Value::Null);
                let _ = tx.send(Ok(result));
            }
        }
        return;
    }

    if parsed.get("method").is_some() {
        let _ = app.emit("rpc_evt", parsed);
    }
}

fn spawn_sidecar(app: tauri::AppHandle) -> Result<RpcState, String> {
    let Some(sidecar_path) = sidecar_candidates().into_iter().next() else {
        return Err("python sidecar not found in src-tauri/binaries".to_string());
    };

    let mut command = Command::new(&sidecar_path);
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(target_os = "windows")]
    {
        // Prevent a separate console window from flashing/opening for the Python sidecar.
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar: {e}"))?;
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "failed to open sidecar stdin".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "failed to open sidecar stdout".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "failed to open sidecar stderr".to_string())?;

    let inner = Arc::new(RpcInner {
        child: Mutex::new(child),
        stdin: Mutex::new(stdin),
        pending: Mutex::new(HashMap::new()),
        next_id: AtomicU64::new(1),
    });

    let app_for_stdout = app.clone();
    let inner_for_stdout = inner.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            match line {
                Ok(line) if !line.trim().is_empty() => {
                    route_sidecar_line(&app_for_stdout, &inner_for_stdout, &line);
                }
                Ok(_) => {}
                Err(err) => {
                    eprintln!("[sidecar:stdout] read error: {err}");
                    break;
                }
            }
        }
        fail_all_pending(&inner_for_stdout, "sidecar stdout closed");
    });

    thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            match line {
                Ok(line) => eprintln!("[sidecar:stderr] {line}"),
                Err(err) => {
                    eprintln!("[sidecar:stderr] read error: {err}");
                    break;
                }
            }
        }
    });

    eprintln!("[sidecar] spawned {}", sidecar_path.display());
    Ok(RpcState { inner })
}

#[tauri::command]
fn rpc_call(method: String, params: Value, state: State<'_, RpcRuntime>) -> Result<Value, String> {
    state.call(method, params)
}

#[tauri::command]
fn rpc_subscribe() -> bool {
    true
}

#[tauri::command]
fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    app.dialog().file().blocking_pick_folder().map(|path| path.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build());

    builder
        .setup(|app| {
            app.manage(RpcRuntime {
                app: app.handle().clone(),
                state: Mutex::new(None),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![rpc_call, rpc_subscribe, pick_folder])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(runtime) = window.try_state::<RpcRuntime>() {
                    if let Ok(mut slot) = runtime.state.lock() {
                        if let Some(state) = slot.take() {
                            if let Ok(mut child) = state.inner.child.lock() {
                                let _ = child.kill();
                            }
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
