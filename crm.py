# ----------------------------------------------------------
# IMPORTACION DE LIBRERIAS Y CONFIGURACION DE LA PAGINA
# ----------------------------------------------------------
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import numpy as np
from st_aggrid import AgGrid, GridOptionsBuilder
import requests
from io import BytesIO

# ----------------------------------------------------------
# FUNCIÓN PARA ORDENAR CÓDIGOS
# ----------------------------------------------------------
def ordenar_codigos_seguro(codigos):
    def clave_ordenacion(x):
        try:
            if isinstance(x, (int, float)):
                return (0, float(x))
            if str(x).replace('.', '', 1).isdigit():
                return (0, float(x))
            return (1, str(x).lower())
        except:
            return (1, str(x).lower())
    
    return sorted(codigos, key=clave_ordenacion)

# ----------------------------------------------------------
# CONFIGURACION DE LA PAGINA
# ----------------------------------------------------------

st.set_page_config(
    page_title="Soporte Televentas",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------------------------------------------------
# Función para cargar datos desde Google Drive
# ----------------------------------------------------------
@st.cache_data
def load_data_from_drive(file_id):
    """Carga y procesa los datos desde Google Drive"""
    try:
        # Construir la URL de descarga directa para archivos de Google Sheets
        download_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
        
        with st.spinner('Cargando datos...'):
            # Descargar el archivo
            response = requests.get(download_url)
            response.raise_for_status()  # Verificar que la descarga fue exitosa
            
            # Leer el archivo Excel
            excel_file = BytesIO(response.content)
            
            # Cargar las hojas de Excel
            pedidos = pd.read_excel(excel_file, sheet_name="pedido")
            entregas = pd.read_excel(excel_file, sheet_name="entregado")
            clientes = pd.read_excel(excel_file, sheet_name="clientes")
            
            # Limpieza de datos
            clientes["direccion"] = clientes["direccion"].astype(str).str.replace('"', '').str.strip()
            
            # Procesar pedidos
            pedidos["fecha_pedido"] = pd.to_datetime(pedidos["fecha_pedido"])
            pedidos["mes_pedido"] = pedidos["fecha_pedido"].dt.to_period('M')
            pedidos["monto"] = pedidos["cantidad"] * pedidos["precio_unitario"]
            
            # Procesar entregas
            entregas["fecha_entrega"] = pd.to_datetime(entregas["fecha_entrega"])
            entregas["mes_entrega"] = entregas["fecha_entrega"].dt.to_period('M')
            
            # Obtener fechas extremas para el pie de página
            fecha_min_pedidos = pedidos["fecha_pedido"].min().strftime('%d/%m/%Y') if not pedidos.empty else "N/A"
            fecha_max_pedidos = pedidos["fecha_pedido"].max().strftime('%d/%m/%Y') if not pedidos.empty else "N/A"
            fecha_min_entregas = entregas["fecha_entrega"].min().strftime('%d/%m/%Y') if not entregas.empty else "N/A"
            fecha_max_entregas = entregas["fecha_entrega"].max().strftime('%d/%m/%Y') if not entregas.empty else "N/A"
            
            # Agregación de pedidos por cliente
            pedidos_agg = pedidos.groupby("codigo_cliente").agg({
                "fecha_pedido": "max",
                "mes_pedido": lambda x: x.value_counts().index[0],
                "monto": ["sum", "mean"],
                "codigo_producto": "count"
            })
            pedidos_agg.columns = ['ultimo_pedido', 'mes_frecuente', 'monto_total', 'ticket_promedio', 'total_pedidos']
            pedidos_agg = pedidos_agg.reset_index()
            
            # Unir datos
            df = pd.merge(clientes, pedidos_agg, on="codigo_cliente", how="left").fillna(0)
            
            # CORRECCIÓN: Cálculo seguro de frecuencia de compra (días desde último pedido)
            hoy = pd.Timestamp.now().normalize()
            df["frecuencia_compra"] = (hoy - pd.to_datetime(df["ultimo_pedido"])).dt.days.fillna(0).astype(int)
            
            # CORRECCIÓN: Limitar frecuencia máxima a 365 días
            df["frecuencia_compra"] = df["frecuencia_compra"].clip(upper=365)
            
            # Calcular efectividad de entrega (pedidos vs entregas)
            entregas_count = entregas.groupby("codigo_cliente").size().reset_index(name='entregas_count')
            df = pd.merge(df, entregas_count, on="codigo_cliente", how="left").fillna(0)
            df["efectividad_entrega"] = (df["entregas_count"] / df["total_pedidos"].replace(0, 1)).clip(0, 1)
            
            # Segmentación automática
            df["segmento"] = pd.cut(
                df["frecuencia_compra"],
                bins=[-1, 30, 90, float('inf')],
                labels=["Activo", "Disminuido", "Inactivo"],
                right=False
            ).astype(str)
            
            # Valor del cliente (proyección anual)
            df["valor_cliente"] = (df["ticket_promedio"] * (365 / df["frecuencia_compra"].replace(0, 1))).round(2)
            
            # Productos top y bottom
            top_productos = (pedidos.groupby("producto")["cantidad"].sum()
                            .nlargest(5).reset_index().dropna())
            bottom_productos = (pedidos.groupby("producto")["cantidad"].sum()
                               .nsmallest(5).reset_index().dropna())
            
            return df, top_productos, bottom_productos, pedidos, entregas, fecha_min_pedidos, fecha_max_pedidos, fecha_min_entregas, fecha_max_entregas
        
    except Exception as e:
        st.error(f"Error al cargar los datos: {str(e)}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "N/A", "N/A", "N/A", "N/A"

# ----------------------------------------------------------
# CARGAR DATOS DESDE GOOGLE DRIVE
# ----------------------------------------------------------

# ID del archivo en Google Drive (extraído de la URL compartida)
# URL proporcionada: https://docs.google.com/spreadsheets/d/1MLgtcblazoKbx0ZwiPljCQxix5bTuKBn/edit?usp=sharing&ouid=117295945155119200843&rtpof=true&sd=true
FILE_ID = "1MLgtcblazoKbx0ZwiPljCQxix5bTuKBn"

# Cargar datos
df, top_productos, bottom_productos, pedidos, entregas, fecha_min_p, fecha_max_p, fecha_min_e, fecha_max_e = load_data_from_drive(FILE_ID)

if df.empty:
    st.warning("No se encontraron datos o hubo un error al cargarlos. Verifica con el administrador.")
    st.stop()

# Sidebar - Filtros
st.sidebar.header("🔍 Filtros Avanzados")
with st.sidebar.expander("Explicación de los filtros"):
    st.write("""
    - **Vendedor (Zona):** Filtra clientes por zona geográfica o vendedor asignado
    - **Segmento:** Clasificación automática según frecuencia de compra
    - **Mes:** Filtra por mes específico de actividad
    """)

# Opciones de filtros
df['zona'] = df.get('zona', 'No especificada').astype(str)
df['segmento'] = df.get('segmento', 'No especificado').astype(str)

# Filtro por mes (convertir a string para evitar problemas)
if not pedidos.empty:
    meses_disponibles = pedidos["mes_pedido"].astype(str).unique()
else:
    meses_disponibles = []

selected_vendedor = st.sidebar.selectbox(
    "Vendedor (Zona)",
    options=["Todos"] + sorted(df["zona"].unique().tolist(), key=str)
)

selected_segmento = st.sidebar.selectbox(
    "Segmento",
    options=["Todos"] + sorted(df["segmento"].unique().tolist(), key=str),
    help="Clasificación basada en frecuencia de compra: Activo (<30 días), Disminuido (30-90 días), Inactivo (>90 días)"
)

selected_mes = st.sidebar.selectbox(
    "Mes",
    options=["Todos"] + sorted(meses_disponibles.tolist()),
    help="Filtrar por mes de actividad"
)

# Filtrado de datos
filtered_df = df.copy()
if selected_vendedor != "Todos":
    filtered_df = filtered_df[filtered_df["zona"] == selected_vendedor]
if selected_segmento != "Todos":
    filtered_df = filtered_df[filtered_df["segmento"] == selected_segmento]
if selected_mes != "Todos":
    filtered_df = filtered_df[filtered_df["mes_frecuente"].astype(str) == selected_mes]

# Pestañas principales
tab1, tab2, tab3, tab4 = st.tabs(["📞 Clientes", "📊 Analítica", "👤 Vendedores", "🔥 Promociones"])

# ----------------------------------------------------------
# PESTAÑA 1: CLIENTES
# ----------------------------------------------------------
with tab1:
    st.header("📞 Gestión de Clientes")
    
    if not filtered_df.empty:
        # Obtener códigos únicos y manejar nulos
        codigos_unicos = filtered_df["codigo_cliente"].dropna().unique()
        
        # Convertir a strings y ordenar
        codigos_options = [""] + ordenar_codigos_seguro([str(cod) for cod in codigos_unicos])
        
        # Selector de códigos
        cliente_search_code = st.selectbox(
            "Seleccione el código del cliente",
            options=codigos_options,
            format_func=lambda x: "Seleccione un código..." if x == "" else x
        )
        
        # Proceso de búsqueda
        if cliente_search_code and cliente_search_code != "":
            try:
                # Búsqueda flexible
                cliente_filtrado = filtered_df[filtered_df["codigo_cliente"].astype(str) == cliente_search_code]
                
                if not cliente_filtrado.empty:
                    cliente_data = cliente_filtrado.iloc[0]
                    
                    # Mostrar datos básicos
                    cols = st.columns(3)
                    with cols[0]:
                        st.info(f"**Nombre:** {cliente_data['nombre']}")
                        st.info(f"**Código:** {cliente_data['codigo_cliente']}")
                        st.info(f"**Teléfono:** {cliente_data['telefono']}")
                    with cols[1]:
                        st.info(f"**Dirección:** {cliente_data['direccion']}")
                        st.info(f"**Tipo negocio:** {cliente_data['tipo_negocio']}")
                    with cols[2]:
                        st.info(f"**Quién atiende:** {cliente_data['quien_atiende']}")
                        st.info(f"**Vendedor (Zona):** {cliente_data['zona']}")
                    
                    # Mostrar KPIs con formato mejorado
                    st.subheader("📊 Indicadores Clave")
                    kpi_cols = st.columns(4)
                    with kpi_cols[0]:
                        st.metric("Ticket promedio", f"RD${cliente_data['ticket_promedio']:,.2f}")
                    with kpi_cols[1]:
                        st.metric("Frecuencia compra", f"{cliente_data['frecuencia_compra']:,.0f} días")
                    with kpi_cols[2]:
                        st.metric("Efectividad entrega", f"{cliente_data['efectividad_entrega']:.2%}")
                    with kpi_cols[3]:
                        estado_color = {"Activo": "normal", "Disminuido": "off", "Inactivo": "inverse"}.get(cliente_data["segmento"], "off")
                        st.metric("Segmento", cliente_data["segmento"], delta_color=estado_color)
                              
                    # ----------------------------------------------------------
                    # SECCIÓN DE ANÁLISIS DE PRODUCTOS
                    # ----------------------------------------------------------
                    st.subheader("🍅 Análisis de Productos", help="Datos históricos de compras y recomendaciones")
                    
                    # Productos del cliente
                    productos_cliente = pedidos[pedidos['codigo_cliente'] == cliente_data['codigo_cliente']]
                    
                    # Top productos del cliente
                    top_productos_cliente = productos_cliente.groupby('producto')['cantidad'].sum().nlargest(5).reset_index()
                    
                    # Productos recomendados (basado en clientes similares)
                    with st.expander("🔍 Método de recomendación"):
                        st.write("""
                        Los productos recomendados se calculan basándose en:
                        1. Clientes con mismo tipo de negocio y zona
                        2. Productos más vendidos entre ese grupo
                        3. Productos que este cliente no compra actualmente
                        """)
                    
                    clientes_similares = filtered_df[
                        (filtered_df['tipo_negocio'] == cliente_data['tipo_negocio']) & 
                        (filtered_df['zona'] == cliente_data['zona'])
                    ]
                    productos_recomendados = pedidos[
                        pedidos['codigo_cliente'].isin(clientes_similares['codigo_cliente'])
                    ].groupby('producto')['cantidad'].sum().nlargest(5).reset_index()
                    
                    # Productos no comprados (oportunidades)
                    todos_productos = pedidos['producto'].unique()
                    productos_no_comprados = [p for p in todos_productos if p not in productos_cliente['producto'].unique()]
                    
                    # Mostrar en 3 columnas
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.markdown("**📦 Productos que más compra**")
                        st.dataframe(top_productos_cliente, hide_index=True)
                        
                    with col2:
                        st.markdown("**💡 Recomendados para su negocio**")
                        st.dataframe(productos_recomendados, hide_index=True)
                        
                    with col3:
                        st.markdown("**🚀 Oportunidades de venta**")
                        st.write(pd.DataFrame({'Productos no comprados': productos_no_comprados[:5]}))
                    
                    # ----------------------------------------------------------
                    # GUÍA DE CONVERSACIÓN COMERCIAL
                    # ----------------------------------------------------------
                    st.subheader("💬 Guía de Ventas", help="Estrategias según perfil del cliente")
                    
                    # Explicación del segmento
                    with st.expander(f"📌 Explicación del segmento: {cliente_data['segmento']}"):
                        if cliente_data['segmento'] == "Activo":
                            st.write("""
                            **Cliente ACTIVO:** Realiza compras frecuentes (última compra hace menos de 30 días)
                            - Estrategia: Fidelización y venta cruzada
                            - Objetivo: Aumentar ticket promedio
                            """)
                        elif cliente_data['segmento'] == "Disminuido":
                            st.write("""
                            **Cliente DISMINUIDO:** Frecuencia de compra reducida (última compra hace 30-90 días)
                            - Estrategia: Reactivación
                            - Objetivo: Recuperar frecuencia histórica
                            """)
                        else:
                            st.write("""
                            **Cliente INACTIVO:** Sin compras recientes (última compra hace más de 90 días)
                            - Estrategia: Recuperación
                            - Objetivo: Primera compra
                            """)
                    
                    # Discurso recomendado
                    if cliente_data['segmento'] == "Activo":
                        st.success("**Discurso recomendado para cliente ACTIVO:**")
                        st.write(f"""
                        "Don/Dña {cliente_data['nombre'].split()[0]}, siempre es un placer atenderle. 
                        Como veo que frecuenta nuestro colmado, quería comentarle sobre **{productos_recomendados.iloc[0]['producto']}** 
                        que está teniendo mucha aceptación. ¿Le interesaría probar una muestra o llevar una cantidad pequeña 
                        con un **5% de descuento** por ser cliente preferencial?"
                        """)
                        
                    elif cliente_data['segmento'] == "Disminuido":
                        st.warning("**Discurso recomendado para cliente DISMINUIDO:**")
                        st.write(f"""
                        "Don/Dña {cliente_data['nombre'].split()[0]}, ¡cuánto tiempo sin atenderle! 
                        Hemos notado que antes solía comprar **{top_productos_cliente.iloc[0]['producto']}** con frecuencia. 
                        Tenemos una **oferta especial** solo para usted este mes. ¿Quiere que le aparte algunas unidades 
                        con un **10% de descuento** para que vuelva a disfrutar de nuestros productos?"
                        """)
                        
                    else:
                        st.error("**Discurso recomendado para cliente INACTIVO:**")
                        st.write(f"""
                        "Don/Dña {cliente_data['nombre'].split()[0]}, espero que esté bien. 
                        Nos hacía falta su visita y queríamos ofrecerle un **descuento especial del 15%** 
                        en su próxima compra más **entrega gratuita**. ¿Qué productos necesita actualmente 
                        para su negocio? Tenemos disponibilidad de **{productos_recomendados.iloc[0]['producto']}** 
                        que podría interesarle."
                        """)
                    
                    # Frecuencia de contacto recomendada
                    st.markdown("**⏰ Frecuencia recomendada de contacto:**")
                    if cliente_data['frecuencia_compra'] < 15:
                        st.write("- Cada 2 semanas (cliente muy activo)")
                    elif cliente_data['frecuencia_compra'] < 30:
                        st.write("- Semanal (mantener engagement)")
                    else:
                        st.write("- 2-3 veces por semana (recuperación urgente)")
                    
                else:
                    st.warning("No se encontró el cliente con el código especificado")
            except Exception as e:
                st.error(f"Error en la búsqueda: {str(e)}")
        else:
            st.info("Seleccione un código de cliente para ver detalles")
    else:
        st.warning("No hay clientes que coincidan con los filtros seleccionados")

# ----------------------------------------------------------
# PESTAÑA 2: ANALÍTICA
# ----------------------------------------------------------
with tab2:
    st.header("📊 Analítica Comercial", help="Métricas y visualizaciones para toma de decisiones")
    
    if not filtered_df.empty:
        # KPIs generales con formato mejorado
        st.subheader("📈 Indicadores Clave")
        metric_cols = st.columns(4)
        with metric_cols[0]:
            st.metric("Clientes totales", filtered_df["codigo_cliente"].nunique())
        with metric_cols[1]:
            st.metric("Compra promedio", f"RD${filtered_df['monto_total'].mean():,.2f}")
        with metric_cols[2]:
            # CORRECCIÓN: Días promedio con límite de 365
            dias_promedio = filtered_df['frecuencia_compra'].mean()
            st.metric("Frecuencia promedio", f"{dias_promedio:,.0f} días")
        with metric_cols[3]:
            st.metric("Valor cliente promedio", f"RD${filtered_df['valor_cliente'].mean():,.2f}")
    
    if not filtered_df.empty:
        # KPIs generales con explicación
        st.subheader("📈 Indicadores Clave")
        with st.expander("ℹ️ Explicación de los KPIs"):
            st.write("""
            - **Clientes totales:** Número único de clientes activos
            - **Compra promedio:** Valor promedio de los pedidos
            - **Frecuencia promedio:** Días entre compras (menos es mejor)
            - **Valor cliente:** Proyección anual de gasto del cliente
            """)
        
        metric_cols = st.columns(4)
        with metric_cols[0]:
            st.metric("Clientes totales", filtered_df["codigo_cliente"].nunique())
        with metric_cols[1]:
            st.metric("Compra promedio", f"${filtered_df['monto_total'].mean():,.2f}")
        with metric_cols[2]:
            st.metric("Frecuencia promedio", f"{filtered_df['frecuencia_compra'].mean():.0f} días")
        with metric_cols[3]:
            st.metric("Valor cliente promedio", f"${filtered_df['valor_cliente'].mean():,.2f}")
        
        # Segmentación de clientes
        st.subheader("🔍 Segmentación de Clientes")
        with st.expander("📌 Cómo se calculan los segmentos"):
            st.write("""
            Los clientes se clasifican automáticamente según días desde su última compra:
            - **Activo:** <30 días
            - **Disminuido:** 30-90 días
            - **Inactivo:** >90 días
            """)
        
        seg_cols = st.columns(2)
        with seg_cols[0]:
            fig = px.pie(filtered_df, names="segmento", title="Distribución por Segmento")
            st.plotly_chart(fig, use_container_width=True)
        with seg_cols[1]:
            fig = px.bar(
                filtered_df.groupby("segmento").agg({"monto_total": "sum", "codigo_cliente": "nunique"}).reset_index(),
                x="segmento",
                y=["monto_total", "codigo_cliente"],
                barmode="group",
                title="Ventas vs Cantidad de Clientes",
                labels={"value": "Cantidad", "variable": "Métrica"}
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Productos más y menos vendidos
        st.subheader("📦 Análisis de Productos")
        with st.expander("ℹ️ Fuente de datos"):
            st.write("""
            Datos calculados a partir del historial completo de pedidos.
            Los productos se ponderan por cantidad vendida.
            """)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🏆 Top 5 Productos**")
            st.dataframe(top_productos, hide_index=True)
        with col2:
            st.markdown("**📉 Bottom 5 Productos**")
            st.dataframe(bottom_productos, hide_index=True)
        
        # Mapa de calor geográfico
        st.subheader("🗺️ Distribución Geográfica")
        with st.expander("ℹ️ Interpretación del mapa"):
            st.write("""
            Los puntos más intensos muestran zonas con mayor concentración de ventas.
            Use este mapa para:
            - Identificar zonas con potencial de crecimiento
            - Optimizar rutas de reparto
            - Planificar campañas geolocalizadas
            """)
        
        # Asegurar coordenadas
        if "lat" not in filtered_df.columns or "lon" not in filtered_df.columns:
            filtered_df["lat"] = 18.5  # RD centro
            filtered_df["lon"] = -69.9
        
        fig = px.density_mapbox(
            filtered_df,
            lat="lat",
            lon="lon",
            z="monto_total",
            radius=20,
            zoom=7,
            mapbox_style="open-street-map",
            hover_name="nombre",
            hover_data=["segmento", "valor_cliente"],
            title="Concentración de Ventas por Zona"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No hay datos que coincidan con los filtros seleccionados")

# ----------------------------------------------------------
# PESTAÑA 3: VENDEDORES
# ----------------------------------------------------------
with tab3:
    st.header("👤 Desempeño de Vendedores", help="Métricas y análisis por vendedor/zona")
    
    if not filtered_df.empty:
        # Estadísticas por vendedor
        st.subheader("📊 Métricas por Vendedor/Zona")
        with st.expander("ℹ️ Cómo interpretar estas métricas"):
            st.write("""
            - **Clientes:** Número de clientes únicos atendidos  
            - **Frecuencia:** Días promedio entre compras de sus clientes  
            - **Efectividad:** % de pedidos entregados satisfactoriamente  
            - **Ticket promedio:** Valor promedio de cada pedido  
            """)
        # Mostrar columnas para debug
        # st.write("Columnas disponibles en filtered_df:", filtered_df.columns.tolist())
        # st.write(filtered_df[["ultimo_pedido", "mes_frecuente"]].head(10))

        # Convierte 'ultimo_pedido' a datetime
        filtered_df["ultimo_pedido"] = pd.to_datetime(filtered_df["ultimo_pedido"], errors='coerce')

        # Estadísticas por vendedor
        vendedor_stats = filtered_df.groupby("zona").agg({
            "nombre": "count",
            "frecuencia_compra": "mean",
            "efectividad_entrega": "mean",
            "ticket_promedio": "mean",
            "valor_cliente": "mean",
            "monto_total": "sum"
        }).reset_index()

        # Redondear métricas
        vendedor_stats["frecuencia_compra"] = vendedor_stats["frecuencia_compra"].round(0)
        vendedor_stats["efectividad_entrega"] = vendedor_stats["efectividad_entrega"] * 100
        vendedor_stats["efectividad_entrega"] = vendedor_stats["efectividad_entrega"].round(2)
        vendedor_stats["ticket_promedio"] = vendedor_stats["ticket_promedio"].round(2)
        vendedor_stats["valor_cliente"] = vendedor_stats["valor_cliente"].round(2)
        vendedor_stats["monto_total"] = vendedor_stats["monto_total"].round(2)

        # Configuración de AgGrid
        gb = GridOptionsBuilder.from_dataframe(vendedor_stats)
        gb.configure_column("zona", 
                            header_name="Vendedor/Zona", 
                            tooltipField="Vendedor/Zona", 
                            headerTooltip="Nombre del vendedor o zona asignada")
        gb.configure_column("nombre", 
                            tooltipField="Clientes", 
                            headerTooltip="Número de clientes únicos atendidos")
        gb.configure_column("frecuencia_compra", 
                            type=["numericColumn"], 
                            precision=0, 
                            valueFormatter='`${value}`',
                            tooltipField="Frecuencia (días)",
                            headerTooltip="Días promedio entre compras de sus clientes")
        gb.configure_column("efectividad_entrega", 
                            valueFormatter='`${value.toLocaleString(undefined, {minimumFractionDigits: 2})}`',
                            tooltipField="Efectividad (%)",
                            headerTooltip="Porcentaje de pedidos entregados satisfactoriamente")
        gb.configure_column("ticket_promedio", 
                            valueFormatter='`$${value.toLocaleString("en-US", {minimumFractionDigits: 2})}`',
                            tooltipField="Ticket Promedio",
                            headerTooltip="Valor promedio de cada pedido")
        gb.configure_column("valor_cliente", 
                            valueFormatter='`$${value.toLocaleString("en-US", {minimumFractionDigits: 2})}`',
                            tooltipField="Valor Cliente",
                            headerTooltip="Proyección anual de gasto del cliente")
        gb.configure_column("monto_total", 
                            valueFormatter='`$${value.toLocaleString("en-US", {minimumFractionDigits: 2})}`',
                            tooltipField="Ventas Totales",
                            headerTooltip="Ventas acumuladas en el período")

        grid_options = gb.build()

        AgGrid(
            vendedor_stats,
            gridOptions=grid_options,
            theme="alpine",  # Puedes usar: "streamlit", "alpine", "material"
            enable_enterprise_modules=False,
            fit_columns_on_grid_load=True
        )
        
        # Gráfico comparativo
        st.subheader("📌 Comparativa de Vendedores")
        fig = px.bar(
            vendedor_stats,
            x="zona",
            y=["monto_total", "valor_cliente"],
            barmode="group",
            title="Ventas Totales vs Valor del Cliente",
            labels={"value": "Monto ($)", "variable": "Métrica"}
        )
        st.plotly_chart(fig, use_container_width=True)

        # Gráfico de tendencia mensual de efectividad
        st.subheader("📈 Tendencia Mensual de Efectividad de Entrega")

        # Filtra solo registros recientes
        fecha_minima = pd.to_datetime("2024-01-01")  # o usar fecha máxima menos 6 meses
        df_efectividad = filtered_df[filtered_df["ultimo_pedido"] >= fecha_minima].copy()

        # Agrupa y calcula
        efectividad_trend = (
            df_efectividad.groupby(pd.Grouper(key="ultimo_pedido", freq="M"))["efectividad_entrega"]
            .mean()
            .reset_index()
        )
        efectividad_trend["efectividad_entrega"] = (efectividad_trend["efectividad_entrega"] * 100).round(2)

        # Gráfico
        fig_tendencia = px.line(
            efectividad_trend,
            x="ultimo_pedido",
            y="efectividad_entrega",
            title="Tendencia Mensual de Efectividad de Entrega (últimos meses)",
            labels={"ultimo_pedido": "Fecha", "efectividad_entrega": "Efectividad (%)"},
            markers=True
        )
        fig_tendencia.update_layout(yaxis=dict(ticksuffix="%"))
        st.plotly_chart(fig_tendencia, use_container_width=True)
        
        # Efectividad por producto
        st.subheader("📦 Productos por Vendedor")
        if not pedidos.empty:
            vendedor_producto = pedidos.groupby(["vendedor", "producto"])["cantidad"].sum().unstack().fillna(0)
            st.dataframe(
                vendedor_producto.style.background_gradient(cmap='YlOrRd'),
                use_container_width=True
            )
    else:
        st.warning("No hay datos de vendedores que coincidan con los filtros seleccionados")

# ----------------------------------------------------------
# PESTAÑA 4: PROMOCIONES
# ----------------------------------------------------------
with tab4:
    st.header("🔥 Estrategias de Promoción", help="Generador de promociones por segmento")
    
    # Promociones por segmento
    st.subheader("🎯 Promociones Segmentadas")
    with st.expander("ℹ️ Cómo usar estas promociones"):
        st.write("""
        Las promociones se generan automáticamente según el perfil del cliente:
        - **Activos:** Programas de fidelización
        - **Disminuidos:** Ofertas de reactivación
        - **Inactivos:** Descuentos agresivos
        """)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**🟢 Para clientes ACTIVOS**")
        st.write("- Programa de puntos (1% cashback)")
        st.write("- Muestras gratis con compras >$5,000")
        st.write("- Descuento del 5% en productos nuevos")
        
    with col2:
        st.markdown("🟡 **Para clientes DISMINUIDOS**")
        st.write("- 10% descuento en pedidos recurrentes")
        st.write("- Envío gratis en próxima compra")
        st.write("- Regalo sorpresa al alcanzar meta")
        
    with col3:
        st.markdown("🔴 **Para clientes INACTIVOS**")
        st.write("- 15% descuento en primera compra")
        st.write("- Entrega express sin costo")
        st.write("- Kit de bienvenida al volver")
    
    # Generador de promociones
    st.subheader("🛠️ Generar Promoción Personalizada")
    with st.expander("ℹ️ Instrucciones"):
        st.write("""
        1. Seleccione un producto
        2. Ajuste el descuento
        3. Defina la fecha límite
        4. Copie el texto generado
        """)
    
    producto_promo = st.selectbox(
        "Producto para promoción",
        options=pedidos['producto'].unique(),
        help="Seleccione el producto a promocionar"
    )
    
    descuento = st.slider(
        "Porcentaje de descuento", 
        min_value=5, 
        max_value=50, 
        value=10,
        help="Descuento a aplicar (5% mínimo para ser atractivo)"
    )
    
    validez = st.date_input(
        "Válido hasta",
        help="Fecha límite para crear sentido de urgencia"
    )
    
    if st.button("Generar texto promocional", help="Clic para generar el mensaje"):
        st.success("**Texto promocional listo para enviar:**")
        st.write(f"""
        "¡Tenemos una oferta especial para usted! 🎉  
        **{descuento}% DE DESCUENTO** en {producto_promo}  
        ⏰ Solo hasta el {validez.strftime('%d/%m/%Y')}  
        📞 Responda a este mensaje con 'SI' para apartar su pedido  
        🚚 Oferta incluye entrega gratuita*  
        
        *Válido para pedidos mayores a RD$2,000. Aplican términos y condiciones."
        """)
        
        st.download_button(
            "Descargar texto",
            data=f"""Oferta especial: {descuento}% en {producto_promo} hasta {validez.strftime('%d/%m/%Y')}""",
            file_name="oferta_promocional.txt"
        )

# Pie de página con información de fechas
st.sidebar.markdown("---")
st.sidebar.info(f"""
**Soporte Televentas** v3.1  
📅 Período de datos:  
Pedidos: {fecha_min_p} - {fecha_max_p}  
Entregas: {fecha_min_e} - {fecha_max_e}  
Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}
""")