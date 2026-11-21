clear; close all; clc;

D = readtable('ensayo.csv');
t = D.t_s;
u = D.u;
omega = D.rpm * 2*pi/60;   % rpm a rad/s

% Buscar la primera fila donde se aplica el freno.
k = find(diff(u) > 0, 1) + 1;
if ~isempty(k)
    t = t - t(k);          % El escalón se aplica en t = 0.
end

figure('Name', 'Ensayo experimental');
tiledlayout(2,1);

nexttile;
stairs(t, u, 'LineWidth', 1.4);
ylabel('Orden de frenado');
ylim([-0.1 1.1]);
grid on;

nexttile;
plot(t, omega, 'LineWidth', 1.4);
xlabel('Tiempo (s)');
ylabel('Velocidad (rad/s)');
grid on;

% Completar con los coeficientes reales del modelo local.
% Entrada de G: cambio de orden de frenado (de 0 a 1 en esta prueba).
% Salida de G: cambio de velocidad angular (rad/s).
num = [];
den = [];
retardo_s = 0;  % Cambiar si el modelo incluye retardo.

if ~isempty(num) && ~isempty(den)
    G = tf(num, den, 'InputDelay', retardo_s);

    figure('Name', 'Respuesta al impulso del modelo');
    impulse(G);
    grid on;

    figure('Name', 'Respuesta al escalón del modelo');
    step(G);
    grid on;
end