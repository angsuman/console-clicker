"""A harmless terminal-shaped window to test real screen capture and Enter."""
import tkinter as tk


class Demo:
    def __init__(self, root):
        self.root = root
        root.title("Clicker demo terminal")
        root.geometry("900x340")
        root.configure(bg="black")
        self.output = tk.Text(root, bg="black", fg="#eeeeee", font=("Courier", 13), relief="flat", padx=18, pady=18, state="disabled")
        self.output.pack(fill="both", expand=True)
        self.accepted = 0
        self.waiting = False
        root.bind("<Return>", self.accept)
        root.bind("<Escape>", lambda event: root.destroy())
        root.after(400, self.prompt)

    def write(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("end", text)
        self.output.configure(state="disabled")

    def prompt(self):
        self.waiting = True
        self.write(f"Requesting permission for:\n    demo operation {self.accepted + 1} (does nothing)\n\nRun this command?\n> 1. Yes, run command\n  2. No, cancel\n\nConfirmations received: {self.accepted}\n")
        self.root.focus_force()

    def accept(self, event=None):
        if self.waiting:
            self.waiting = False
            self.accepted += 1
            self.write(f"Enter received. Confirmations: {self.accepted}\n\nDoing harmless pretend work…\nNext prompt in 4 seconds. Escape closes this demo.")
            self.root.after(4000, self.prompt)
