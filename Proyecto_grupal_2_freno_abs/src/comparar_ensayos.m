function comparar_ensayos()
% Busca los dos CSV más recientes en la carpeta actual de MATLAB.
archivo_m = csv_mas_reciente('ensayo_m_*.csv');
archivo_b = csv_mas_reciente('ensayo_b_*.csv');

fprintf('Giro libre: %s\n', archivo_m);
fprintf('Con freno:  %s\n', archivo_b);

M = readtable(archivo_m, 'TextType', 'string');
B = readtable(archivo_b, 'TextType', 'string');

[t_m, omega_m] = alinear_al_apagado(M);
[t_b, omega_b] = alinear_al_apagado(B);

% Figura 1: comparación de las mediciones de la ESP32.
figure('Name', 'Comparación experimental');
plot(t_m, omega_m, 'o-', 'DisplayName', 'Giro libre (m)');
hold on;
plot(t_b, omega_b, 's-', 'DisplayName', 'Con freno (b)');
xline(0, '--', 'Motor apagado', 'HandleVisibility', 'off');
grid on;
xlabel('Tiempo respecto al apagado del motor (s)');
ylabel('Velocidad angular (rad/s)');
legend('Location', 'best');

% Estima b/J_eq usando el CSV de giro libre seleccionado.
% Se omite la primera ventana si cruza el instante de apagado.
usar = t_m >= 0.5 & omega_m > 0;
if nnz(usar) < 3
    warning('Hay muy pocas muestras de giro libre para ajustar el modelo.');
    return;
end

ajuste = polyfit(t_m(usar), log(omega_m(usar)), 1);
tasa = -ajuste(1);
if tasa <= 0
    warning('El ajuste no produjo una tasa de desaceleración positiva.');
    return;
end

% Aproximación de las dos piezas como un disco uniforme.
radio_m = 0.125;  % Para 250 mm de diámetro. 
masa_kg = 0.285;
J_eq = 0.5 * masa_kg * radio_m^2;
b_viscoso = tasa * J_eq;

fprintf('b/J_eq = %.4f 1/s\n', tasa);
fprintf('b aproximado = %.4g N*m*s/rad\n', b_viscoso);

% Figura 2: respuesta al impulso del modelo del punto 5.
% Figura 2: respuesta al impulso calculada con el modelo del punto 5.
% Figura 2: respuesta al impulso del modelo de frenado.
G = tf(-1, [J_eq, b_viscoso]);

figure('Name', 'Respuesta al impulso');
impulse(G);
grid on;
title('Respuesta al impulso del modelo de frenado');
end

function archivo = csv_mas_reciente(patron)
lista = dir(patron);
assert(~isempty(lista), 'No se encontró un CSV con el patrón %s.', patron);

[~, indice] = max([lista.datenum]);
archivo = fullfile(lista(indice).folder, lista(indice).name);
end

function [t, omega] = alinear_al_apagado(D)
apagado = D.tipo == "evento" & startsWith(D.detalle, "MOTOR APAGADO");
k = find(apagado, 1);
assert(~isempty(k), 'El CSV no contiene la marca MOTOR APAGADO.');

muestra = D.tipo == "muestra";
t = D.tiempo_s(muestra) - D.tiempo_s(k);
omega = D.omega_rad_s(muestra);
end



