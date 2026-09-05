"""La molette d'une fenêtre fille ne fait pas défiler le panneau principal.

Rapporté : *« si on roule la molette dans la fenêtre Generated PI template, ça
bouge aussi la principale. »*

`bind_all` pose son gestionnaire sur l'étiquette « all » de Tk : il se déclenche
pour n'importe quel widget de l'application, pas seulement pour ceux de la
fenêtre où il a été installé. Le garde vérifie donc le toplevel de l'événement.
Vrai de toutes les fenêtres filles — édition, historique, scanner — et pas
seulement de celle qui a été rapportée.

Utilisation :  python tests/wheel_scope_smoke.py
"""
import os, sys, time, tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import PI

def run(app, root, done):
    rep=[]
    def ok(l,c,d=""): rep.append((bool(c),l,d))
    app.product_combo.set("Coolant  [P2]"); app._on_product_pick()
    app.chain_var.set("P1 → P2 (Factory)"); app.planet_var.set("Barren")
    app.cc_var.set(5); app._on_chain_changed(); app._update_bom()
    root.update(); app._generate(); root.update()

    canvas=None
    for w in root.winfo_children():
        for c in _all(w):
            if isinstance(c, tk.Canvas) and hasattr(c,"_pi_doc"): canvas=c
    ok("the popup map exists", canvas is not None)
    if canvas is None: return _finish(rep,done)

    # Le panneau ne déborde plus tout seul : la fenêtre s'ajuste à son contenu,
    # et c'est exactement ce qu'on lui demande. Il faut donc créer la condition
    # à la main — une fenêtre trop courte — pour avoir quelque chose à faire
    # défiler et pouvoir vérifier *qui* défile.
    # Il faut *annuler* l'ajustement en attente, pas seulement remplacer la
    # méthode : `after` retient l'objet méthode déjà lié, donc réassigner
    # l'attribut ne change rien à ce qui est en file, et la fenêtre se reposait
    # à sa taille juste après le rétrécissement.
    pending = getattr(app, "_fit_job", None)
    if pending:
        root.after_cancel(pending)
        app._fit_job = None
    app._schedule_fit = lambda: None
    root.geometry(f"{root.winfo_width()}x480")
    end = time.time() + 0.4
    while time.time() < end:
        root.update()
        time.sleep(0.01)

    # le viewport defilant du panneau principal
    vp=[c for c in _all(root) if isinstance(c,tk.Canvas) and c.winfo_toplevel() is root
        and not hasattr(c,"_pi_doc")]
    vp=[c for c in vp if c.yview()!=(0.0,1.0)]
    ok("the main panel has something to scroll", bool(vp),
       {"canvases":len(vp), "root_h":root.winfo_height()})
    if not vp: return _finish(rep,done)
    viewport=vp[0]
    before=viewport.yview()

    canvas.event_generate("<MouseWheel>", delta=-120, x=50, y=50)
    root.update()
    ok("scrolling the popup map leaves the main panel alone",
       viewport.yview()==before, {"before":before,"after":viewport.yview()})

    # et la molette dans la fenetre principale doit toujours marcher
    viewport.event_generate("<MouseWheel>", delta=-120, x=10, y=10)
    root.update()
    ok("the main panel still scrolls on its own wheel",
       viewport.yview()!=before, {"after":viewport.yview()})
    _finish(rep,done)

def _finish(rep,done):
    p=sum(1 for g,_,_ in rep if g)
    for g,l,d in rep: print(f"{'PASS' if g else 'FAIL'}  {l}   {d if d else ''}")
    print(f"\n{p}/{len(rep)} checks passed"); done(p==len(rep))

def _all(w,out=None):
    out=[] if out is None else out
    for c in w.winfo_children(): out.append(c); _all(c,out)
    return out

root=tk.Tk(); app=PI.PIGeneratorApp(root); st={"c":1}
def done(g): st["c"]=0 if g else 1; root.quit()
root.after(400, lambda: run(app,root,done)); root.mainloop()
try: root.destroy()
except tk.TclError: pass
sys.exit(st["c"])
