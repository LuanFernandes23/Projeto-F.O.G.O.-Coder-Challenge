// Aviso sonoro curto para alertas críticos (gerado via Web Audio, sem arquivo de áudio).
let context: AudioContext | undefined;

export function playAlertSound(): void {
  try {
    context ??= new AudioContext();
    const now = context.currentTime;
    [0, 0.18].forEach((offset) => {
      const oscillator = context!.createOscillator();
      const gain = context!.createGain();
      oscillator.type = "triangle";
      oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.25, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.15);
      oscillator.connect(gain).connect(context!.destination);
      oscillator.start(now + offset);
      oscillator.stop(now + offset + 0.16);
    });
  } catch {
    /* navegador sem Web Audio ou bloqueado: o toast já avisa visualmente */
  }
}
