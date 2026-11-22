function archivo = capturar_ensayo(puerto, comando)
% Envía b, m o f a la ESP32. Guarda las mediciones y los eventos en un CSV.

    comando = lower(string(comando));
    assert(isscalar(comando) && any(comando == ["b", "m", "f"]), ...
        'Usá b para frenado, m para giro libre o f para solo el freno.');

    esp = serialport(puerto, 115200, 'Timeout', 1);
    configureTerminator(esp, "LF");

    % Algunas placas se reinician cuando MATLAB abre el puerto.
    pause(2);
    flush(esp, "input");

    % Cada fila puede ser una medición de velocidad o un evento del ensayo.
    tiempo_s = zeros(0,1);
    tipo = strings(0,1);
    pulsos = zeros(0,1);
    rpm = zeros(0,1);
    detalle = strings(0,1);

    iniciado = false;
    completo = false;

    patronEvento = '^([\d.]+) s \| EVENTO \| (.+)$';
    patronMuestra = ['^Tiempo: ([\d.]+) s \| Pulsos: (\d+)' ...
                     ' \| RPM: ([\d.]+) \| Estado: (.+)$'];

    writeline(esp, comando);
    reloj = tic;

    % b y m duran alrededor de 17 s. Dejamos margen para recibir el final.
    while toc(reloj) < 30
        if esp.NumBytesAvailable == 0
            pause(0.02);
            continue;
        end

        linea = strip(string(readline(esp)));
        if isempty(linea) || ismissing(linea)
            continue;
        end

        evento = regexp(char(linea), patronEvento, 'tokens', 'once');

        if ~isempty(evento)
            mensaje = string(evento{2});

            % Ignora mensajes anteriores a la marca de inicio.
            if ~iniciado
                iniciado = startsWith(mensaje, "INICIO");
                if ~iniciado
                    continue;
                end
            end

            tiempo_s(end+1,1) = str2double(evento{1});
            tipo(end+1,1) = "evento";
            pulsos(end+1,1) = NaN;
            rpm(end+1,1) = NaN;
            detalle(end+1,1) = mensaje;

            if mensaje == "FIN DE PRUEBA"
                completo = true;
                break;
            end
            continue;
        end

        muestra = regexp(char(linea), patronMuestra, 'tokens', 'once');
        if iniciado && ~isempty(muestra)
            tiempo_s(end+1,1) = str2double(muestra{1});
            tipo(end+1,1) = "muestra";
            pulsos(end+1,1) = str2double(muestra{2});
            rpm(end+1,1) = str2double(muestra{3});
            detalle(end+1,1) = string(muestra{4});
        end
    end

    % Libera el puerto para que se pueda ejecutar otro ensayo.
    clear esp

    if ~iniciado
        error('No llegó la marca INICIO. Revisá el puerto y el sketch cargado.');
    end

    omega_rad_s = rpm * 2*pi/60;
    D = table(tiempo_s, tipo, pulsos, rpm, omega_rad_s, detalle);

    % La fecha, hora y milisegundos distinguen ejecuciones del mismo comando.
    marca = string(datetime('now', 'Format', 'yyyyMMdd_HHmmss_SSS'));
    archivo = "ensayo_" + comando + "_" + marca + ".csv";
    if ~completo
        archivo = "parcial_" + archivo;
    end

    writetable(D, archivo);
    fprintf('CSV guardado en %s\n', fullfile(pwd, archivo));

    if ~completo
        warning('El registro quedó parcial porque faltó FIN DE PRUEBA.');
    end

    esMuestra = D.tipo == "muestra";
    if ~any(esMuestra)
        warning('El CSV contiene eventos, pero faltan mediciones de RPM.');
        return;
    end

    esEvento = D.tipo == "evento";
    if comando == "f"
        cambio = find(esEvento & D.detalle == "FRENO CERRADO", 1);
    else
        cambio = find(esEvento & startsWith(D.detalle, "MOTOR APAGADO"), 1);
    end

    % Alinea b y m con el apagado del motor. Para f, usa el cierre del freno.
    t0 = 0;
    if ~isempty(cambio)
        t0 = D.tiempo_s(cambio);
    end

    figure('Name', char(archivo));
    plot(D.tiempo_s(esMuestra) - t0, D.omega_rad_s(esMuestra), 'o-', ...
        'LineWidth', 1.2);
    grid on;
    xlabel('Tiempo respecto al cambio de orden (s)');
    ylabel('Velocidad angular (rad/s)');
    title("Prueba " + comando, 'Interpreter', 'none');

    if ~isempty(cambio)
        xline(0, '--', D.detalle(cambio));
    else
        xlabel('Tiempo desde el inicio de la prueba (s)');
    end
end